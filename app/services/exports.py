import asyncio
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (Attachment, BatchFile, Document, DocumentRevision, DocumentSource, Encounter, RelatedEncounter,
                        CareTopic, CareTopicEncounter, CareTopicExclusion, CareSuggestion, CareRevision,
                        LabResult, Medication, MedicationEvent, MedicationPackage, MedicationSource, MedicationRevision,
                        MetricDefinition, MetricEntry, MetricEntryRevision, ReceiptDetail, SourceUnit, TestSession,
                        TestSessionSource, UploadBatch, UploadCareContext, User)
from app.services.storage import ObjectStorage


async def create_user_export(db: AsyncSession, storage: ObjectStorage, user: User) -> BytesIO:
    documents = list((await db.scalars(select(Document).where(Document.owner_id == user.id))).all())
    labs = list((await db.scalars(select(LabResult).where(LabResult.owner_id == user.id))).all())
    medications = list((await db.scalars(select(Medication).where(Medication.owner_id == user.id))).all())
    sources = list((await db.scalars(select(MedicationSource).where(MedicationSource.owner_id == user.id))).all())
    events = list((await db.scalars(select(MedicationEvent).where(MedicationEvent.owner_id == user.id))).all())
    attachments = list((await db.scalars(select(Attachment).where(Attachment.owner_id == user.id))).all())
    batches = list((await db.scalars(select(UploadBatch).where(UploadBatch.owner_id == user.id))).all())
    care_contexts = list((await db.scalars(select(UploadCareContext).where(UploadCareContext.owner_id == user.id))).all())
    sources_v2 = list((await db.scalars(select(SourceUnit).where(SourceUnit.owner_id == user.id))).all())
    document_sources = list((await db.scalars(select(DocumentSource).where(DocumentSource.owner_id == user.id))).all())
    encounters = list((await db.scalars(select(Encounter).where(Encounter.owner_id == user.id))).all())
    related_encounters = list((await db.scalars(select(RelatedEncounter).where(RelatedEncounter.owner_id == user.id))).all())
    care_topics = list((await db.scalars(select(CareTopic).where(CareTopic.owner_id == user.id))).all())
    care_links = list((await db.scalars(select(CareTopicEncounter).where(CareTopicEncounter.owner_id == user.id))).all())
    care_exclusions = list((await db.scalars(select(CareTopicExclusion).where(CareTopicExclusion.owner_id == user.id))).all())
    care_suggestions = list((await db.scalars(select(CareSuggestion).where(CareSuggestion.owner_id == user.id))).all())
    care_revisions = list((await db.scalars(select(CareRevision).where(CareRevision.owner_id == user.id))).all())
    packages = list((await db.scalars(select(MedicationPackage).where(MedicationPackage.owner_id == user.id))).all())
    batch_files = list((await db.scalars(select(BatchFile).where(BatchFile.owner_id == user.id))).all())
    receipts = list((await db.scalars(select(ReceiptDetail).where(ReceiptDetail.owner_id == user.id))).all())
    metric_definitions = list((await db.scalars(select(MetricDefinition).where(MetricDefinition.owner_id == user.id))).all())
    metric_entries = list((await db.scalars(select(MetricEntry).where(MetricEntry.owner_id == user.id))).all())
    test_sessions = list((await db.scalars(select(TestSession).where(TestSession.owner_id == user.id))).all())
    test_session_sources = list((await db.scalars(select(TestSessionSource).where(TestSessionSource.owner_id == user.id))).all())
    revisions = list((await db.scalars(select(DocumentRevision).where(DocumentRevision.owner_id == user.id))).all())
    medication_revisions = list((await db.scalars(select(MedicationRevision).where(MedicationRevision.owner_id == user.id))).all())
    metric_entry_revisions = list((await db.scalars(select(MetricEntryRevision).where(MetricEntryRevision.owner_id == user.id))).all())

    manifest = {
        "schema_version": "health_archive_export.v5",
        "owner": {"id": str(user.id), "email": user.email if user.managed_by_id is None else None,
                  "name": user.profile_name if user.managed_by_id is not None else '我'},
        "documents": [{
            "id": str(item.id), "document_type": item.document_type, "title": item.title,
            "primary_date": item.primary_date.isoformat() if item.primary_date else None,
            "primary_date_raw": item.primary_date_raw, "hospital": item.hospital,
            "department": item.department, "doctor": item.doctor,
            "amount": str(item.amount) if item.amount is not None else None,
            "key_information": item.key_information, "parsed_content": item.parsed_content,
            "encounter_id": str(item.encounter_id) if item.encounter_id else None,
            "extraction_metadata": item.extraction_metadata,
            "type_specific_data": item.type_specific_data, "patient_scope": item.patient_scope,
            "version": item.version, "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
        } for item in documents],
        "lab_results": [{
            "id": str(item.id), "document_id": str(item.document_id), "name": item.name,
            "result": item.result, "unit": item.unit, "reference_range": item.reference_range,
            "flag": item.flag, "source_page": item.source_page, "source_quote": item.source_quote,
            "analyte_key": item.analyte_key, "specimen": item.specimen, "condition": item.condition,
            "observed_date": item.observed_date.isoformat() if item.observed_date else None,
            "timepoint_minutes": item.timepoint_minutes, "test_session_key": item.test_session_key,
            "test_session_id": str(item.test_session_id) if item.test_session_id else None,
            "source_unit_id": str(item.source_unit_id) if item.source_unit_id else None,
            "result_type": item.result_type, "review_status": item.review_status,
        } for item in labs],
        "medications": [{
            "id": str(item.id), "drug_key": item.drug_key, "name": item.name,
            "status": item.status, "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "dose_each_time": item.dose_each_time, "frequency": item.frequency,
            "timing": item.timing, "version": item.version,
            "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
            "generic_name": item.generic_name, "brand_name": item.brand_name, "strength": item.strength,
            "dosage_form": item.dosage_form, "manufacturer": item.manufacturer, "approval_number": item.approval_number,
            "quantity": item.quantity, "route": item.route,
            "start_date": item.start_date.isoformat() if item.start_date else None,
            "planned_end_date": item.planned_end_date.isoformat() if item.planned_end_date else None,
        } for item in medications],
        "medication_sources": [{
            "id": str(item.id), "medication_id": str(item.medication_id),
            "document_id": str(item.document_id), "instructions": item.instructions,
            "purpose_text": item.purpose_text, "source_data": item.source_data,
        } for item in sources],
        "medication_events": [{
            "id": str(item.id), "medication_id": str(item.medication_id),
            "event_type": item.event_type, "event_date": item.event_date.isoformat(),
            "from_status": item.from_status, "to_status": item.to_status,
            "dose_each_time": item.dose_each_time, "frequency": item.frequency,
            "timing": item.timing, "note": item.note,
        } for item in events],
        "attachments": [{
            "id": str(item.id), "document_id": str(item.document_id) if item.document_id else None,
            "filename": item.filename, "mime_type": item.mime_type,
            "size_bytes": item.size_bytes, "sha256": item.sha256,
        } for item in attachments],
    }

    manifest['batches'] = [{'id': str(b.id), 'status': b.status, 'version': b.version, 'grouping': b.grouping,
                            'care_context_id':str(b.care_context_id) if b.care_context_id else None,
                            'original_payload': b.original_payload, 'payload': b.payload, 'result': b.result} for b in batches]
    from app.services.upload_care import context_json
    manifest['upload_care_contexts'] = [context_json(context) for context in care_contexts]
    manifest['batch_files'] = [{'id': str(f.id), 'batch_id': str(f.batch_id), 'attachment_id': str(f.attachment_id),
                                'ordinal': f.ordinal, 'client_file_id': f.client_file_id} for f in batch_files]
    manifest['source_units'] = [{'id': str(s.id), 'batch_id': str(s.batch_id), 'attachment_id': str(s.attachment_id),
                                 'page_index': s.page_index, 'ordinal': s.ordinal, 'kind': s.kind, 'label': s.label} for s in sources_v2]
    manifest['document_sources'] = [{'document_id': str(s.document_id), 'source_unit_id': str(s.source_unit_id)} for s in document_sources]
    manifest['encounters'] = [{'id': str(v.id), 'title': v.title, 'date': v.date.isoformat() if v.date else None,
                               'primary_topic_id': str(v.primary_topic_id) if v.primary_topic_id else None,
                               'hospital': v.hospital, 'patient_identity': v.patient_identity, 'evidence': v.evidence,
                               'event_kind': v.event_kind, 'department': v.department,
                               'date_end': v.date_end.isoformat() if v.date_end else None,
                               'date_basis': v.date_basis, 'date_sources': v.date_sources,
                               'summary_facts': v.summary_facts, 'milestones': v.milestones,
                               'user_note': v.user_note, 'version': v.version,
                               'deleted_at': v.deleted_at.isoformat() if v.deleted_at else None} for v in encounters]
    manifest['related_encounters'] = [{'document_id': str(link.document_id), 'encounter_id': str(link.encounter_id)}
                                      for link in related_encounters]
    manifest['care_topics'] = [{'id': str(x.id), 'name': x.name, 'note': x.note, 'status': x.status,
        'origin': x.origin, 'analysis_fingerprint': x.analysis_fingerprint,
        'version': x.version, 'deleted_at': x.deleted_at.isoformat() if x.deleted_at else None} for x in care_topics]
    manifest['care_topic_encounters'] = [{'topic_id': str(x.topic_id), 'encounter_id': str(x.encounter_id),
        'origin': x.origin, 'evidence': x.evidence} for x in care_links]
    manifest['care_topic_exclusions'] = [{'topic_id': str(x.topic_id), 'encounter_id': str(x.encounter_id)}
        for x in care_exclusions]
    manifest['care_suggestions'] = [{'id': str(x.id), 'kind': x.kind, 'dedupe_key': x.dedupe_key,
        'payload': x.payload, 'source_versions': x.source_versions, 'status': x.status,
        'version': x.version} for x in care_suggestions]
    manifest['care_revisions'] = [{'id': str(x.id), 'object_kind': x.object_kind, 'object_id': str(x.object_id),
        'from_version': x.from_version, 'snapshot': x.snapshot, 'changed_fields': x.changed_fields,
        'changed_by_id': str(x.changed_by_id), 'created_at': x.created_at.isoformat()} for x in care_revisions]
    manifest['medication_packages'] = [{'id': str(p.id), 'medication_id': str(p.medication_id), 'document_id': str(p.document_id),
                                      'batch_number': p.batch_number, 'expiry_date': p.expiry_date.isoformat() if p.expiry_date else None,
                                      'quantity_raw': p.quantity_raw, 'source_data': p.source_data} for p in packages]
    manifest['receipt_details'] = [{
        'id': str(x.id), 'document_id': str(x.document_id), 'receipt_number': x.receipt_number,
        'receipt_identity': x.receipt_identity,
        'total_amount': str(x.total_amount) if x.total_amount is not None else None,
        'insurance_amount': str(x.insurance_amount) if x.insurance_amount is not None else None,
        'personal_amount': str(x.personal_amount) if x.personal_amount is not None else None,
        'currency': x.currency, 'settlement_time': x.settlement_time,
        'payment_method': x.payment_method, 'line_items': x.line_items, 'status': x.status,
        'duplicate_of_id': str(x.duplicate_of_id) if x.duplicate_of_id else None, 'version': x.version,
    } for x in receipts]
    manifest['metric_definitions'] = [{
        'id': str(x.id), 'key': x.key, 'name': x.name, 'group': x.group_name,
        'record_type': x.record_type, 'unit': x.unit, 'aliases': x.aliases,
        'component_labels': x.component_labels, 'followed': x.followed,
        'sort_order': x.sort_order, 'preset': x.preset, 'version': x.version,
    } for x in metric_definitions]
    manifest['metric_entries'] = [{
        'id': str(x.id), 'metric_id': str(x.metric_id), 'record_date': x.record_date.isoformat(),
        'raw_value': x.raw_value, 'value1': str(x.value1) if x.value1 is not None else None,
        'value2': str(x.value2) if x.value2 is not None else None, 'text_value': x.text_value,
        'unit': x.unit, 'condition': x.condition, 'review_status': x.review_status,
        'note': x.note, 'idempotency_key': x.idempotency_key, 'version': x.version,
        'voided_at': x.voided_at.isoformat() if x.voided_at else None,
    } for x in metric_entries]
    manifest['test_sessions'] = [{
        'id': str(x.id), 'name': x.name, 'session_date': x.session_date.isoformat() if x.session_date else None,
        'hospital': x.hospital, 'notes': x.notes, 'version': x.version,
    } for x in test_sessions]
    manifest['test_session_sources'] = [{
        'id': str(x.id), 'test_session_id': str(x.test_session_id), 'source_unit_id': str(x.source_unit_id),
    } for x in test_session_sources]
    manifest['document_revisions'] = [{
        'id': str(x.id), 'document_id': str(x.document_id), 'changed_by_id': str(x.changed_by_id),
        'from_version': x.from_version, 'snapshot': x.snapshot, 'changed_fields': x.changed_fields,
        'created_at': x.created_at.isoformat(),
    } for x in revisions]
    manifest['medication_revisions'] = [{
        'id': str(x.id), 'medication_id': str(x.medication_id), 'changed_by_id': str(x.changed_by_id),
        'from_version': x.from_version, 'snapshot': x.snapshot, 'changed_fields': x.changed_fields,
        'created_at': x.created_at.isoformat(),
    } for x in medication_revisions]
    manifest['metric_entry_revisions'] = [{
        'id': str(x.id), 'metric_entry_id': str(x.metric_entry_id), 'changed_by_id': str(x.changed_by_id),
        'from_version': x.from_version, 'snapshot': x.snapshot, 'changed_fields': x.changed_fields,
        'created_at': x.created_at.isoformat(),
    } for x in metric_entry_revisions]
    output = BytesIO()
    used_names = set()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for attachment in attachments:
            base = Path(attachment.filename).name or str(attachment.id)
            name = f"attachments/{base}"
            if name in used_names:
                name = f"attachments/{attachment.id}-{base}"
            used_names.add(name)
            next(item for item in manifest['attachments'] if item['id'] == str(attachment.id))['archive_path'] = name
            stream = await storage.get(attachment.object_key)
            data = await asyncio.to_thread(stream.read)
            close = getattr(stream, "close", None)
            if close:
                await asyncio.to_thread(close)
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    output.seek(0)
    return output
