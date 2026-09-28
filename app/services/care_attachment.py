"""Attach sources without copying them or collapsing separate hospital visits."""
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Document, Encounter
from app.services.care_history import classify_document, document_date_basis
from app.services.care_hierarchy import set_parent


async def attach_source_documents(db, user, topic, document_ids):
    ids = set(document_ids)
    if not ids:
        return []
    docs = list((await db.scalars(select(Document).where(Document.id.in_(ids),
        Document.owner_id == user.id, Document.deleted_at.is_(None))
        .order_by(Document.id).with_for_update())).all())
    if len(docs) != len(ids):
        raise HTTPException(404, '选定资料不存在')
    events = {}
    for doc in docs:
        if doc.encounter_id:
            event = await db.scalar(select(Encounter).where(Encounter.id == doc.encounter_id,
                Encounter.owner_id == user.id, Encounter.deleted_at.is_(None)).with_for_update())
            if event is None:
                raise HTTPException(409, '资料所属诊疗已移入回收站，请先恢复')
        else:
            event = Encounter(owner_id=user.id, title=doc.title, hospital=doc.hospital,
                department=doc.department, date=doc.primary_date,
                date_basis=document_date_basis(doc),
                event_kind=classify_document(doc.document_type) or 'other')
            db.add(event)
            await db.flush()
            doc.encounter_id = event.id
            # Grouping does not change source content or its extraction version.
        events[event.id] = event
    for event_id in sorted(events, key=str):
        await set_parent(db, user, events[event_id], topic)
    return list(events)
