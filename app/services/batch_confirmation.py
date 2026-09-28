import hashlib
import json
import unicodedata
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.batch_schemas import BatchExtraction, validate_sources
from app.currency import parse_amount
from app.models import SourceUnit, Document, DocumentSource, Encounter, LabResult, Medication, MedicationPackage, MedicationSource, ReceiptDetail
from app.services.medications import restore_from_new_source
from app.services.care_history import create_event_for_document, derived_facts, classify_document
from app.services.care_topics import organize_topics
from app.services.upload_care import batch_context, group_target, bind_document


def historical_source(documents, mention):
    """Never attach a historical claim to a document without matching source text."""
    text = mention.strip()
    if not text:
        return None
    for document in documents:
        for index, line in enumerate(document.key_information or []):
            if isinstance(line, str) and text in line:
                return document, f'document.key_information.{index}'
        parsed = document.parsed_content
        content = parsed if isinstance(parsed, str) else json.dumps(parsed, ensure_ascii=False) if parsed else ''
        if text in content:
            return document, 'document.parsed_content'
    return None


def identity_key(med):
    fields = [med.name, med.strength, med.dosage_form, med.manufacturer]
    if not all(fields):
        return 'unresolved:' + str(uuid.uuid4())
    normalized = [unicodedata.normalize('NFKC', x).strip().casefold() for x in fields]
    normalized.append(unicodedata.normalize('NFKC', med.approval_number or '').strip().casefold())
    return 'product:' + hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode()).hexdigest()


async def resolve_medication(db, user, item):
    if item.existing_medication_id:
        med = await db.scalar(select(Medication).where(Medication.id == item.existing_medication_id, Medication.owner_id == user.id))
        if not med:
            raise HTTPException(404, '选中的已有药品不存在')
        # Choosing an existing record must not accidentally conflate strengths or manufacturers.
        for field in ['name', 'strength', 'dosage_form', 'manufacturer', 'approval_number']:
            a, b = getattr(med, field), getattr(item, field)
            if a and b and unicodedata.normalize('NFKC', a).strip() != unicodedata.normalize('NFKC', b).strip():
                raise HTTPException(422, f'已有药品的 {field} 与本次内容冲突，请核对')
        restore_from_new_source(db, user, med)
        return med
    key = identity_key(item)
    med = await db.scalar(select(Medication).where(Medication.owner_id == user.id, Medication.drug_key == key))
    if med:
        restore_from_new_source(db, user, med)
        return med
    try:
        async with db.begin_nested():
            med = Medication(owner_id=user.id, drug_key=key, status='备用药', **{
                name: getattr(item, name) for name in ['name', 'generic_name', 'brand_name', 'strength', 'dosage_form',
                                                      'manufacturer', 'approval_number', 'route']})
            db.add(med)
            await db.flush()
        return med
    except IntegrityError:
        med = await db.scalar(select(Medication).where(Medication.owner_id == user.id, Medication.drug_key == key))
        if not med:
            raise
        restore_from_new_source(db, user, med)
        return med


async def confirm(db, user, batch):
    try:
        payload = BatchExtraction.model_validate(batch.payload)
        source_ids = {str(x) for x in (await db.scalars(select(SourceUnit.id).where(SourceUnit.batch_id == batch.id,
                                                                                  SourceUnit.owner_id == user.id))).all()}
        context = await batch_context(db, user.id, batch, lock=True)
        validation_payload = payload.model_copy(deep=True)
        for group in validation_payload.groups:
            if group_target(batch, context, group.id).mode in ('archive', 'existing_event'):
                group.encounter_id = None
        validate_sources(validation_payload, source_ids, confirm=True)
        visits = {}
        existing_visit_ids = set()
        revised_events = set()
        small_events = {}
        for v in sorted(payload.encounters, key=lambda item: (str(item.existing_encounter_id or ''), item.id)):
            members = [g for g in payload.groups if g.encounter_id == v.id and
                group_target(batch, context, g.id).mode not in ('archive', 'existing_event') and not (
                    group_target(batch, context, g.id).mode == 'small' and (context or
                    (batch.grouping or {}).get('care_targets', {}).get(g.id)))]
            if not members:
                continue
            targets = {(group_target(batch, context, g.id).mode,
                str(group_target(batch, context, g.id).topic_id)) for g in members}
            if len(targets) > 1:
                raise HTTPException(422, '同次诊疗的资料归属不同，请先拆分诊疗分组')
            if v.existing_encounter_id:
                encounter = await db.scalar(select(Encounter).where(Encounter.id == v.existing_encounter_id,
                    Encounter.owner_id == user.id, Encounter.deleted_at.is_(None)).with_for_update()
                    .execution_options(populate_existing=True))
                if not encounter:
                    raise HTTPException(404, '已有就诊记录不存在')
                existing_visit_ids.add(encounter.id)
            else:
                encounter = Encounter(owner_id=user.id, title=v.title, hospital=v.hospital, date=v.date,
                                      date_end=v.date_end, date_basis=(v.date_basis if v.date_basis != 'unknown' else 'user_confirmed') if v.date else 'unknown',
                                      department=v.department, event_kind=v.event_kind,
                                      patient_identity=v.patient_identity, evidence=v.evidence,
                                      summary_facts=[], milestones=[])
                db.add(encounter)
                await db.flush()
            visits[v.id] = encounter.id
        documents, medications, confirmed_labs = [], set(), []
        for group in payload.groups:
            amount = None
            if group.document.amount:
                try:
                    amount = parse_amount(group.document.amount)
                except ValueError as error:
                    raise HTTPException(422, f'{group.document.title} 的金额格式不正确') from error
            receipt = group.document.details.receipt
            if receipt and receipt.total_amount is not None:
                if amount is not None and amount != receipt.total_amount:
                    raise HTTPException(422, f'{group.document.title} 的总金额字段存在冲突，请核对')
                amount = receipt.total_amount
            values = group.document.model_dump(exclude={'type', 'amount', 'source_refs', 'details', 'patient_scope'})
            document = Document(owner_id=user.id, document_type=group.document.type, amount=amount,
                encounter_id=visits.get(group.encounter_id), extraction_metadata={
                    'batch_id': str(batch.id), 'group_id': group.id, 'kind': group.kind,
                    'patient_identity': group.patient_identity, 'evidence': [x.model_dump() for x in group.evidence],
                    'review_items': group.review_items, 'model_patient_scope': group.document.patient_scope},
                    type_specific_data=group.document.details.model_dump(mode='json'),
                    patient_scope='self', **values)
            db.add(document)
            await db.flush()
            event = await bind_document(db, user, batch, context, group, document, revised_events, small_events)
            if event and group.encounter_id:
                visits[group.encounter_id] = event.id
            documents.append(str(document.id))
            if receipt or (group.document.type == '医疗发票 / 收费单' and amount is not None):
                receipt = receipt or group.document.details.receipt
                db.add(ReceiptDetail(owner_id=user.id, document_id=document.id,
                    receipt_number=receipt.receipt_number if receipt else None,
                    total_amount=receipt.total_amount if receipt and receipt.total_amount is not None else amount,
                    insurance_amount=receipt.insurance_amount if receipt else None,
                    personal_amount=receipt.personal_amount if receipt else None,
                    currency=receipt.currency if receipt else 'CNY',
                    settlement_time=receipt.settlement_time if receipt else None,
                    payment_method=receipt.payment_method if receipt else None,
                    line_items=[x.model_dump(mode='json') for x in receipt.line_items] if receipt else []))
            for sid in group.source_ids:
                db.add(DocumentSource(owner_id=user.id, document_id=document.id, source_unit_id=uuid.UUID(sid)))
            for lab in group.lab_results:
                lab_values = lab.model_dump(exclude={'source_ref', 'source_id'})
                result = LabResult(owner_id=user.id, document_id=document.id, **lab_values,
                    source_unit_id=uuid.UUID(lab.source_id) if lab.source_id else None,
                    source_page=lab.source_ref.page if lab.source_ref else None, source_quote=lab.source_ref.quote if lab.source_ref else None)
                db.add(result)
                if document.patient_scope == 'self':
                    confirmed_labs.append(result)
            for item in group.medications:
                med = await resolve_medication(db, user, item)
                medications.add(str(med.id))
                db.add(MedicationSource(owner_id=user.id, medication_id=med.id, document_id=document.id,
                    instructions=item.instructions, purpose_text=item.purpose_text,
                    source_data={**item.model_dump(mode='json'), 'source_ids': group.source_ids}))
                for package in item.packages:
                    db.add(MedicationPackage(owner_id=user.id, medication_id=med.id, document_id=document.id,
                        batch_number=package.batch_number, expiry_date=package.expiry_date, quantity_raw=package.quantity_raw,
                        source_data={'source_ids': package.source_ids or group.source_ids}))
        if confirmed_labs:
            await db.flush()
            from app.services.test_session_grouping import group_confirmed_test_results
            await group_confirmed_test_results(db, user.id, [uuid.UUID(document_id) for document_id in documents])
            from app.services.metric_discovery import discover_metrics
            await discover_metrics(db, user.id, confirmed_labs)
        for visit in payload.encounters:
            encounter_id = visits.get(visit.id)
            if not encounter_id:
                continue
            encounter = await db.get(Encounter, encounter_id)
            members = [document for document in (await db.scalars(select(Document).where(
                Document.owner_id == user.id, Document.encounter_id == encounter_id,
                Document.deleted_at.is_(None)))).all()]
            if members and (not encounter.summary_facts or all(
                str(fact.get('id', '')).startswith('document-') for fact in encounter.summary_facts)):
                encounter.summary_facts = derived_facts(members, 2)
            if encounter.event_kind == 'other' and members:
                encounter.event_kind = next((kind for member in members
                    if (kind := classify_document(member.document_type))), 'other')
            if visit.historical_mentions and members:
                previous = {fact.get('text') for fact in encounter.summary_facts or []}
                new_facts = list(encounter.summary_facts or [])
                for index, mention in enumerate(visit.historical_mentions):
                    text = f'原文提及既往：{mention.strip()}'
                    if text in previous or not mention.strip():
                        continue
                    match = historical_source(members, mention)
                    if not match:
                        continue
                    source, field = match
                    new_facts.append({'id': f'history-{source.id}-{index}', 'text': text,
                        'origin': 'source', 'category': 'historical_reference',
                        'source_refs': [{'document_id': str(source.id), 'source_unit_id': None,
                            'page': None, 'field': field,
                            'quote': mention.strip(), 'document_version': source.version}]})
                encounter.summary_facts = new_facts
            if visit.date and not encounter.date_sources:
                refs = []
                for group in payload.groups:
                    if group.encounter_id != visit.id:
                        continue
                    source_doc = next((item for item in members if (item.extraction_metadata or {}).get('group_id') == group.id), None)
                    if not source_doc:
                        continue
                    for evidence in group.evidence:
                        if 'date' not in evidence.field.lower() and '日期' not in evidence.field:
                            continue
                        source_unit = await db.scalar(select(SourceUnit).where(SourceUnit.id == uuid.UUID(evidence.source_id),
                            SourceUnit.owner_id == user.id))
                        refs.append({'document_id': str(source_doc.id), 'source_unit_id': evidence.source_id,
                            'page': source_unit.page_index + 1 if source_unit and source_unit.page_index is not None else None,
                            'field': evidence.field, 'quote': evidence.quote,
                            'document_version': source_doc.version})
                encounter.date_sources = refs[:10]
            if encounter.id in existing_visit_ids:
                encounter.version += 1
        linked_ids = (await db.scalars(select(Document.encounter_id).where(Document.id.in_([uuid.UUID(x) for x in documents]),
            Document.encounter_id.is_not(None)))).all()
        result = {'document_ids': documents, 'medication_ids': sorted(medications), 'encounter_ids': list(dict.fromkeys(str(x) for x in linked_ids))}
        batch.result, batch.status = result, 'archived'
        batch.version += 1
        await organize_topics(db, user.id)
        await db.commit()
        return result
    except ValueError as error:
        await db.rollback()
        raise HTTPException(422, str(error)) from error
    except Exception:
        await db.rollback()
        raise
