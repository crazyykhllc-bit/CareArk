from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import Field, field_validator

from app.db import get_db
from app.dependencies import get_current_user
from app.document_schemas import DocumentDetails
from app.models import Attachment, Document, DocumentRevision, DocumentSource, SourceUnit, LabResult, ReceiptDetail, User
from app.schemas import StrictModel
from app.services.image_previews import preview_urls

router = APIRouter(prefix="/api/documents")


class DocumentUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    document_type: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    primary_date: date | None = None
    primary_date_raw: str | None = Field(default=None, max_length=100)
    hospital: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    doctor: str | None = Field(default=None, max_length=200)
    amount: Decimal | None = None
    key_information: list[str] | None = None
    parsed_content: str | None = None
    patient_scope: Literal['self', 'other', 'unconfirmed'] | None = None
    type_specific_data: dict | None = None

    @field_validator('document_type', 'title')
    @classmethod
    def required_fields_cannot_be_null(cls, value):
        if value is None or not value.strip():
            raise ValueError('必填字段不能设为空')
        return value.strip()

    @field_validator('key_information', 'patient_scope', 'type_specific_data')
    @classmethod
    def required_shapes_cannot_be_null(cls, value):
        if value is None:
            raise ValueError('必填字段不能设为空')
        return value

    @field_validator('amount')
    @classmethod
    def amount_must_be_finite(cls, value):
        if value is not None and not value.is_finite():
            raise ValueError('金额必须是有限十进制数')
        return value


def document_json(document: Document) -> dict:
    return {
        "id": str(document.id),
        "document_type": document.document_type,
        "title": document.title,
        "primary_date": document.primary_date.isoformat() if document.primary_date else None,
        "primary_date_raw": document.primary_date_raw,
        "hospital": document.hospital,
        "department": document.department,
        "doctor": document.doctor,
        "amount": str(document.amount) if document.amount is not None else None,
        "key_information": document.key_information,
        "parsed_content": document.parsed_content,
        "encounter_id": str(document.encounter_id) if document.encounter_id else None,
        "version": document.version,
        "deleted_at": document.deleted_at.isoformat() if document.deleted_at else None,
        "patient_scope": document.patient_scope,
        "type_specific_data": document.type_specific_data,
    }


@router.patch('/{document_id}')
async def update_document(document_id: UUID, data: DocumentUpdate,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    document = await db.scalar(select(Document).where(Document.id == document_id,
        Document.owner_id == user.id, Document.deleted_at.is_(None)).with_for_update())
    if not document:
        raise HTTPException(404, '健康档案不存在')
    if document.version != data.expected_version:
        raise HTTPException(409, '档案已更新，请刷新后再保存')
    fields = data.model_fields_set - {'expected_version'}
    if not fields:
        return document_json(document)
    snapshot = document_json(document)
    values = data.model_dump(exclude={'expected_version'}, exclude_unset=True)
    parsed_details = None
    if 'type_specific_data' in values:
        parsed_details = DocumentDetails.model_validate(values['type_specific_data'])
        receipt_details = parsed_details.receipt
        if receipt_details:
            supplied_amount = values.get('amount') if 'amount' in values else receipt_details.total_amount
            if supplied_amount is not None and receipt_details.total_amount is not None and supplied_amount != receipt_details.total_amount:
                raise HTTPException(422, '总金额字段存在冲突，请核对')
            if receipt_details.total_amount is None and 'amount' in values:
                receipt_details.total_amount = supplied_amount
            values['amount'] = receipt_details.total_amount
        values['type_specific_data'] = parsed_details.model_dump(mode='json')

    receipt = None
    if 'amount' in values or (parsed_details and parsed_details.receipt):
        receipt = await db.scalar(select(ReceiptDetail).where(ReceiptDetail.document_id == document.id,
                                                               ReceiptDetail.owner_id == user.id).with_for_update())
    if parsed_details and parsed_details.receipt:
        details = parsed_details.receipt
        if not receipt:
            receipt = ReceiptDetail(owner_id=user.id, document_id=document.id)
            db.add(receipt)
        receipt.receipt_number = details.receipt_number
        receipt.total_amount = details.total_amount
        receipt.insurance_amount = details.insurance_amount
        receipt.personal_amount = details.personal_amount
        receipt.currency = details.currency
        receipt.settlement_time = details.settlement_time
        receipt.payment_method = details.payment_method
        receipt.line_items = [item.model_dump(mode='json') for item in details.line_items]
        if receipt.id:
            receipt.version += 1
    elif receipt and 'amount' in values:
        receipt.total_amount = values['amount']
        receipt.version += 1
        stored_details = dict(document.type_specific_data or {})
        stored_receipt = dict(stored_details.get('receipt') or {})
        stored_receipt['total_amount'] = str(values['amount']) if values['amount'] is not None else None
        stored_details['receipt'] = stored_receipt
        values['type_specific_data'] = stored_details
    for name, value in values.items():
        setattr(document, name, value)
    if snapshot['patient_scope'] != 'self' and document.patient_scope == 'self':
        labs = (await db.scalars(select(LabResult).where(
            LabResult.document_id == document.id, LabResult.owner_id == user.id,
            LabResult.review_status == 'confirmed'))).all()
        if labs:
            from app.services.test_session_grouping import group_confirmed_test_results
            from app.services.metric_discovery import discover_metrics
            await group_confirmed_test_results(db, user.id, [document.id])
            await discover_metrics(db, user.id, labs)
    db.add(DocumentRevision(owner_id=user.id, document_id=document.id, changed_by_id=user.id,
                            from_version=document.version, snapshot=snapshot,
                            changed_fields=sorted(fields)))
    document.version += 1
    from app.services.care_topics import organize_topics
    await organize_topics(db, user.id)
    await db.commit()
    return document_json(document)


@router.get('/{document_id}/revisions')
async def list_document_revisions(document_id: UUID, user: User = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)) -> dict:
    exists = await db.scalar(select(Document.id).where(Document.id == document_id, Document.owner_id == user.id))
    if not exists:
        raise HTTPException(404, '健康档案不存在')
    rows = (await db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == document_id,
        DocumentRevision.owner_id == user.id).order_by(DocumentRevision.created_at.desc()))).all()
    return {'items': [{'id': str(row.id), 'from_version': row.from_version,
                       'changed_fields': row.changed_fields, 'snapshot': row.snapshot,
                       'created_at': row.created_at.isoformat()} for row in rows]}


class DocumentLifecycleUpdate(StrictModel):
    expected_version: int = Field(ge=1)


class LabResultUpdate(StrictModel):
    expected_document_version: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=300)
    result: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=100)
    reference_range: str | None = Field(default=None, max_length=200)
    flag: str | None = Field(default=None, max_length=30)
    observed_date: date | None = None
    condition: str | None = Field(default=None, max_length=200)

    @field_validator('name')
    @classmethod
    def name_cannot_be_blank(cls, value):
        if value is None or not value.strip():
            raise ValueError('检验项目名称不能为空')
        return value.strip()


@router.get('/trash')
async def list_trashed_documents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Document).where(Document.owner_id == user.id,
        Document.deleted_at.is_not(None)).order_by(Document.deleted_at.desc()))).all()
    return {'items': [document_json(row) for row in rows]}


async def change_document_trash(document_id, expected_version, restore, user, db):
    document = await db.scalar(select(Document).where(Document.id == document_id,
        Document.owner_id == user.id).with_for_update())
    if not document:
        raise HTTPException(404, '健康档案不存在')
    if document.version != expected_version:
        raise HTTPException(409, '档案已更新，请刷新后重试')
    if (document.deleted_at is None) == restore:
        raise HTTPException(409, '档案状态已变化，请刷新')
    snapshot = document_json(document)
    document.deleted_at = None if restore else datetime.now(timezone.utc)
    db.add(DocumentRevision(owner_id=user.id, document_id=document.id, changed_by_id=user.id,
                            from_version=document.version, snapshot=snapshot,
                            changed_fields=['deleted_at']))
    document.version += 1
    from app.services.care_topics import organize_topics
    await organize_topics(db, user.id)
    await db.commit()
    return document_json(document)


@router.post('/{document_id}/trash')
async def trash_document(document_id: UUID, data: DocumentLifecycleUpdate,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await change_document_trash(document_id, data.expected_version, False, user, db)


@router.post('/{document_id}/restore')
async def restore_document(document_id: UUID, data: DocumentLifecycleUpdate,
                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await change_document_trash(document_id, data.expected_version, True, user, db)


@router.patch('/{document_id}/lab-results/{lab_id}')
async def update_lab_result(document_id: UUID, lab_id: UUID, data: LabResultUpdate,
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    document = await db.scalar(select(Document).where(Document.id == document_id,
        Document.owner_id == user.id, Document.deleted_at.is_(None)).with_for_update())
    if not document:
        raise HTTPException(404, '健康档案不存在')
    if document.version != data.expected_document_version:
        raise HTTPException(409, '档案已更新，请刷新后再保存')
    lab = await db.scalar(select(LabResult).where(LabResult.id == lab_id,
        LabResult.document_id == document_id, LabResult.owner_id == user.id).with_for_update())
    if not lab:
        raise HTTPException(404, '检验项目不存在')
    values = data.model_dump(exclude={'expected_document_version'}, exclude_unset=True)
    if not values:
        return document_json(document)
    snapshot = document_json(document)
    snapshot['lab_result'] = {
        'id': str(lab.id), 'name': lab.name, 'result': lab.result, 'unit': lab.unit,
        'reference_range': lab.reference_range, 'flag': lab.flag,
        'observed_date': lab.observed_date.isoformat() if lab.observed_date else None,
        'condition': lab.condition,
    }
    db.add(DocumentRevision(owner_id=user.id, document_id=document.id, changed_by_id=user.id,
        from_version=document.version, snapshot=snapshot,
        changed_fields=[f'lab_result:{lab.id}:{key}' for key in sorted(values)]))
    for key, value in values.items():
        setattr(lab, key, value)
    if 'result' in values:
        from app.services.metric_matching import parse_strict_number, parse_strict_pair
        lab.result_type = 'numeric' if parse_strict_number(lab.result) is not None or parse_strict_pair(lab.result) else 'text'
    document.version += 1
    if document.patient_scope == 'self' and lab.review_status == 'confirmed':
        from app.services.metric_discovery import discover_metrics
        await discover_metrics(db, user.id, [lab])
    await db.commit()
    return document_json(document)


@router.get("")
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: int = Query(default=0, ge=0),
    search: str | None = None,
) -> dict:
    query = select(Document).where(Document.owner_id == user.id, Document.deleted_at.is_(None))
    if search:
        term = f"%{search}%"
        query = query.where(or_(Document.title.ilike(term), Document.hospital.ilike(term)))
    query = query.order_by(Document.primary_date.desc(), Document.created_at.desc(), Document.id.desc()).offset(cursor).limit(limit + 1)
    rows = list((await db.scalars(query)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [document_json(row) for row in rows], "next_cursor": cursor + limit if has_more else None}


@router.get("/{document_id}")
async def get_document(document_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    document = await db.scalar(select(Document).where(Document.id == document_id, Document.owner_id == user.id))
    if not document:
        raise HTTPException(404, "健康档案不存在")
    labs = (await db.scalars(select(LabResult).where(LabResult.document_id == document.id, LabResult.owner_id == user.id).order_by(LabResult.created_at))).all()
    attachments = (await db.scalars(select(Attachment).where(Attachment.document_id == document.id, Attachment.owner_id == user.id))).all()
    source_rows = (await db.execute(select(SourceUnit, Attachment).join(DocumentSource, DocumentSource.source_unit_id == SourceUnit.id)
        .join(Attachment, Attachment.id == SourceUnit.attachment_id).where(DocumentSource.document_id == document.id,
        SourceUnit.owner_id == user.id, Attachment.owner_id == user.id).order_by(SourceUnit.created_at, SourceUnit.ordinal))).all()
    result = document_json(document)
    result["lab_results"] = [{
        "id": str(item.id), "name": item.name, "result": item.result, "unit": item.unit,
        "reference_range": item.reference_range, "flag": item.flag,
        "source_page": item.source_page, "source_quote": item.source_quote,
        "analyte_key": item.analyte_key, "specimen": item.specimen,
        "condition": item.condition,
        "observed_date": item.observed_date.isoformat() if item.observed_date else None,
        "timepoint_minutes": item.timepoint_minutes, "test_session_key": item.test_session_key,
        "source_id": str(item.source_unit_id) if item.source_unit_id else None,
        "result_type": item.result_type, "review_status": item.review_status,
    } for item in labs]
    result["attachments"] = [{
        "id": str(item.id), "filename": item.filename, "mime_type": item.mime_type,
        "content_url": f"/api/attachments/{item.id}/content",
        **preview_urls(item),
    } for item in attachments]
    for source, attachment in source_rows:
        # Retain page-specific links; a PDF can supply multiple logical documents.
        result['attachments'].append({'id': str(attachment.id), 'source_id': str(source.id),
            'filename': source.label, 'mime_type': attachment.mime_type, 'page_index': source.page_index,
            'content_url': f'/api/attachments/{attachment.id}/content' + (f'#page={source.page_index}' if source.page_index and attachment.mime_type == 'application/pdf' else ''), **preview_urls(attachment)})
    result['extraction_metadata'] = document.extraction_metadata
    receipt = await db.scalar(select(ReceiptDetail).where(ReceiptDetail.document_id == document.id,
                                                          ReceiptDetail.owner_id == user.id))
    result['receipt'] = None if not receipt else {
        'receipt_number': receipt.receipt_number,
        'total_amount': str(receipt.total_amount) if receipt.total_amount is not None else None,
        'insurance_amount': str(receipt.insurance_amount) if receipt.insurance_amount is not None else None,
        'personal_amount': str(receipt.personal_amount) if receipt.personal_amount is not None else None,
        'currency': receipt.currency, 'settlement_time': receipt.settlement_time,
        'payment_method': receipt.payment_method, 'line_items': receipt.line_items,
        'status': receipt.status, 'duplicate_of_id': str(receipt.duplicate_of_id) if receipt.duplicate_of_id else None,
    }
    return result
