"""Conservative, versioned organization proposals for existing records."""

import hashlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import CareSuggestion, CareTopic, CareTopicEncounter, CareTopicExclusion, Document, Encounter, RelatedEncounter
from app.services.care_history import classify_document, create_event_for_document, document_date_basis
from app.services.care_topics import organize_topics


def suggestion_key(kind: str, ids: list[str]) -> str:
    return hashlib.sha256((kind + ':' + ':'.join(sorted(ids))).encode()).hexdigest()


async def prepare_suggestions(db, owner_id, *, apply=False) -> dict:
    """Generate only proposals; never relink old documents or merge events."""
    documents = (await db.scalars(select(Document).where(Document.owner_id == owner_id,
        Document.deleted_at.is_(None), Document.encounter_id.is_(None)))).all()
    proposals = []
    for document in documents:
        kind = classify_document(document.document_type)
        if kind:
            proposals.append(('document_event', [str(document.id)],
                {'document_id': str(document.id), 'title': document.title, 'hospital': document.hospital,
                 'date': document.primary_date.isoformat() if document.primary_date else None,
                 'event_kind': kind, 'date_basis': document_date_basis(document)},
                {str(document.id): document.version}))
    related = (await db.execute(select(RelatedEncounter, Document).join(Document,
        Document.id == RelatedEncounter.document_id).where(RelatedEncounter.owner_id == owner_id,
        Document.owner_id == owner_id, Document.deleted_at.is_(None), Document.encounter_id.is_not(None),
        Document.encounter_id != RelatedEncounter.encounter_id))).all()
    for link, document in related:
        events = (await db.scalars(select(Encounter).where(Encounter.owner_id == owner_id,
            Encounter.deleted_at.is_(None), Encounter.id.in_([document.encounter_id, link.encounter_id])))).all()
        if len(events) != 2:
            continue
        ids = [str(item.id) for item in events]
        proposals.append(('topic_relation', ids,
            {'event_ids': ids, 'source_document_id': str(document.id)},
            {str(item.id): item.version for item in events} | {str(document.id): document.version}))
    created = 0
    for kind, ids, payload, versions in proposals:
        key = suggestion_key(kind, ids)
        existing = await db.scalar(select(CareSuggestion).where(CareSuggestion.owner_id == owner_id,
            CareSuggestion.dedupe_key == key))
        if existing:
            if existing.status in ('dismissed', 'outdated') and existing.source_versions != versions:
                if apply:
                    existing.payload = payload
                    existing.source_versions = versions
                    existing.status = 'pending'
                    existing.version += 1
                created += 1
            continue
        if apply:
            db.add(CareSuggestion(owner_id=owner_id, kind=kind, dedupe_key=key,
                payload=payload, source_versions=versions, status='pending'))
        created += 1
    if apply:
        await db.commit()
    return {'eligible_documents': len(documents), 'candidate_count': len(proposals), 'created': created}


async def accept_suggestion(db, user, suggestion: CareSuggestion, *, title=None, date=None,
                            date_provided=False, date_basis=None):
    if suggestion.status == 'accepted':
        return {'id': str(suggestion.id), 'status': 'accepted'}
    if suggestion.status != 'pending':
        raise HTTPException(409, '这项建议已处理')
    if suggestion.kind == 'document_event':
        doc_id = suggestion.payload['document_id']
        doc = await db.scalar(select(Document).where(Document.id == UUID(doc_id),
            Document.owner_id == user.id, Document.deleted_at.is_(None)).with_for_update())
        if not doc or doc.version != suggestion.source_versions.get(doc_id) or doc.encounter_id:
            suggestion.status = 'outdated'
            await db.commit()
            raise HTTPException(409, '来源资料已变化，请重新整理')
        event = await create_event_for_document(db, user.id, doc)
        if not event:
            raise HTTPException(422, '这份资料不适合单独建立诊疗事件')
        if title is not None:
            event.title = title.strip()
        if date_provided or date_basis is not None:
            if date_provided:
                event.date = date
            event.date_basis = (date_basis or 'user_confirmed') if event.date else 'unknown'
            event.date_sources = []
        suggestion.payload = {**suggestion.payload, 'created_event_id': str(event.id)}
    elif suggestion.kind == 'topic_relation':
        name = (title or '').strip()
        if not name:
            raise HTTPException(422, {'field': 'title', 'message': '请为跨院诊疗主题命名'})
        event_ids = suggestion.payload['event_ids']
        events = (await db.scalars(select(Encounter).where(Encounter.owner_id == user.id,
            Encounter.deleted_at.is_(None), Encounter.id.in_([UUID(item) for item in event_ids])))).all()
        source_id = suggestion.payload['source_document_id']
        document = await db.scalar(select(Document).where(Document.id == UUID(source_id), Document.owner_id == user.id,
            Document.deleted_at.is_(None)))
        if len(events) != len(event_ids) or not document or any(
            event.version != suggestion.source_versions.get(str(event.id)) for event in events) or document.version != suggestion.source_versions.get(source_id):
            suggestion.status = 'outdated'
            await db.commit()
            raise HTTPException(409, '关联来源已变化，请重新核对')
        topic = CareTopic(owner_id=user.id, name=name, status='active')
        db.add(topic)
        await db.flush()
        for event in events:
            from app.services.care_hierarchy import set_parent
            await set_parent(db,user,event,topic,reference=event.primary_topic_id is not None)
        suggestion.payload = {**suggestion.payload, 'created_topic_id': str(topic.id)}
    elif suggestion.kind == 'topic_membership':
        payload = suggestion.payload
        topic = await db.scalar(select(CareTopic).where(CareTopic.id == UUID(payload['topic_id']),
            CareTopic.owner_id == user.id, CareTopic.deleted_at.is_(None)))
        event = await db.scalar(select(Encounter).where(Encounter.id == UUID(payload['event_id']),
            Encounter.owner_id == user.id, Encounter.deleted_at.is_(None)))
        document = await db.scalar(select(Document).where(Document.id == UUID(payload['document_id']),
            Document.owner_id == user.id, Document.deleted_at.is_(None)))
        if not topic or not event or not document or document.encounter_id != event.id or (
            topic.name != payload['topic_name'] or
            event.version != suggestion.source_versions.get(str(event.id)) or
            document.version != suggestion.source_versions.get(str(document.id))):
            suggestion.status = 'outdated'
            await db.commit()
            raise HTTPException(409, '主题或来源资料已变化，请重新研判')
        if await db.scalar(select(CareTopicExclusion.id).where(CareTopicExclusion.owner_id == user.id,
            CareTopicExclusion.topic_id == topic.id, CareTopicExclusion.encounter_id == event.id)):
            raise HTTPException(409, '你已手动移除这条关联；可在事件详情中重新勾选')
        if not await db.scalar(select(CareTopicEncounter.id).where(CareTopicEncounter.owner_id == user.id,
            CareTopicEncounter.topic_id == topic.id, CareTopicEncounter.encounter_id == event.id)):
            db.add(CareTopicEncounter(owner_id=user.id, topic_id=topic.id, encounter_id=event.id,
                origin='manual', evidence={'reason': 'accepted_model_suggestion',
                    'document_id': str(document.id), 'quote': payload['quote']}))
        if event.primary_topic_id is None:
            from app.services.care_hierarchy import set_parent
            await db.flush()
            await set_parent(db,user,event,topic)
    else:
        raise HTTPException(422, '无法识别的整理建议')
    suggestion.status = 'accepted'
    suggestion.version += 1
    await organize_topics(db, user.id)
    await db.commit()
    return {'id': str(suggestion.id), 'status': suggestion.status, 'result': suggestion.payload}
