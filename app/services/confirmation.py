from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attachment,
    Document,
    ExtractionDraft as DraftRecord,
    ExtractionJob,
    LabResult,
    Medication,
    MedicationSource,
    ReceiptDetail,
    SourceUnit,
    User,
)
from app.schemas import ExtractionDraft
from app.currency import parse_amount
from app.services.care_history import create_event_for_document
from app.services.care_topics import organize_topics


async def confirm_draft(db: AsyncSession, user: User, draft_id: UUID, payload: dict) -> Document:
    record = await db.scalar(
        select(DraftRecord).where(DraftRecord.id == draft_id, DraftRecord.owner_id == user.id).with_for_update()
    )
    if not record:
        raise HTTPException(404, "待确认资料不存在")
    if record.status != "pending":
        raise HTTPException(409, "这份资料已经处理")
    draft = ExtractionDraft.model_validate(payload)
    amount = None
    if draft.document.amount:
        try:
            amount = parse_amount(draft.document.amount)
        except ValueError as error:
            raise HTTPException(422, "金额格式不正确") from error
    try:
        try:
            source_ids = {UUID(item.source_id) for item in draft.lab_results if item.source_id}
        except (ValueError, TypeError, AttributeError) as error:
            raise HTTPException(422, '检验结果来源编号格式不正确') from error
        if source_ids:
            owned_source_ids = set((await db.scalars(select(SourceUnit.id).where(
                SourceUnit.owner_id == user.id, SourceUnit.id.in_(source_ids)))).all())
            if owned_source_ids != source_ids:
                raise HTTPException(422, '检验结果包含不存在或不属于当前用户的来源')
        details = draft.document.details
        receipt = details.receipt
        if receipt and receipt.total_amount is not None:
            if amount is not None and amount != receipt.total_amount:
                raise HTTPException(422, "总金额字段存在冲突，请核对")
            amount = receipt.total_amount
        document = Document(
            owner_id=user.id,
            document_type=draft.document.type,
            title=draft.document.title,
            primary_date=draft.document.primary_date,
            primary_date_raw=draft.document.primary_date_raw,
            hospital=draft.document.hospital,
            department=draft.document.department,
            doctor=draft.document.doctor,
            amount=amount,
            key_information=draft.document.key_information,
            parsed_content=draft.document.parsed_content,
            extraction_metadata={"review_items": draft.review_items},
            type_specific_data=details.model_dump(mode="json"),
            patient_scope=draft.document.patient_scope,
        )
        db.add(document)
        await db.flush()
        await create_event_for_document(db, user.id, document)
        job = await db.get(ExtractionJob, record.job_id)
        attachment = await db.get(Attachment, job.attachment_id)
        attachment.document_id = document.id
        if receipt or (draft.document.type == '医疗发票 / 收费单' and amount is not None):
            db.add(ReceiptDetail(owner_id=user.id, document_id=document.id,
                receipt_number=receipt.receipt_number if receipt else None,
                total_amount=receipt.total_amount if receipt and receipt.total_amount is not None else amount,
                insurance_amount=receipt.insurance_amount if receipt else None,
                personal_amount=receipt.personal_amount if receipt else None,
                currency=receipt.currency if receipt else 'CNY',
                settlement_time=receipt.settlement_time if receipt else None,
                payment_method=receipt.payment_method if receipt else None,
                line_items=[x.model_dump(mode='json') for x in receipt.line_items] if receipt else []))
        confirmed_labs = []
        for item in draft.lab_results:
            values = item.model_dump(exclude={"source_ref", "source_id"})
            lab = LabResult(
                owner_id=user.id,
                document_id=document.id,
                **values,
                source_unit_id=UUID(item.source_id) if item.source_id else None,
                source_page=item.source_ref.page if item.source_ref else None,
                source_quote=item.source_ref.quote if item.source_ref else None,
            )
            db.add(lab)
            confirmed_labs.append(lab)
        if document.patient_scope == 'self' and confirmed_labs:
            await db.flush()
            from app.services.test_session_grouping import group_confirmed_test_results
            await group_confirmed_test_results(db, user.id, [document.id])
            from app.services.metric_discovery import discover_metrics
            await discover_metrics(db, user.id, confirmed_labs)
        for item in draft.medications:
            medication = await db.scalar(select(Medication).where(Medication.owner_id == user.id, Medication.drug_key == item.drug_key))
            if not medication:
                medication = Medication(
                    owner_id=user.id,
                    drug_key=item.drug_key,
                    name=item.name,
                    generic_name=item.generic_name,
                    brand_name=item.brand_name,
                    strength=item.strength,
                    dosage_form=item.dosage_form,
                    expiry_date=item.expiry_date,
                    quantity=item.quantity,
                    route=item.route,
                    status="备用药",
                )
                db.add(medication)
                await db.flush()
            else:
                from app.services.medications import restore_from_new_source
                restore_from_new_source(db, user, medication)
            db.add(MedicationSource(
                owner_id=user.id,
                medication_id=medication.id,
                document_id=document.id,
                instructions=item.instructions,
                purpose_text=item.purpose_text,
                source_data=item.model_dump(mode="json"),
            ))
        record.revised_payload = draft.model_dump(mode="json")
        record.status = "confirmed"
        from app.models import utcnow
        record.confirmed_at = utcnow()
        job.status = "archived"
        await organize_topics(db, user.id)
        await db.commit()
        await db.refresh(document)
        return document
    except Exception:
        await db.rollback()
        raise
