"""Recycle a whole care group and restore only objects changed by that action."""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import CareRevision, Document, DocumentRevision, Encounter, utcnow
from app.api.archive import document_json
from app.services.care_hierarchy import record_revision


async def trash_group(db,user,topic):
    events = list((await db.scalars(select(Encounter).where(Encounter.owner_id == user.id,
        Encounter.primary_topic_id == topic.id,Encounter.deleted_at.is_(None))
        .order_by(Encounter.id).with_for_update())).all())
    docs = list((await db.scalars(select(Document).where(Document.owner_id == user.id,
        Document.encounter_id.in_([x.id for x in events]),Document.deleted_at.is_(None))
        .order_by(Document.id).with_for_update())).all())
    from app.api.care_history import snapshot_topic
    snapshot = snapshot_topic(topic)
    snapshot['group_events'] = [{'id':str(x.id),'version':x.version+1} for x in events]
    snapshot['group_documents'] = [{'id':str(x.id),'version':x.version+1} for x in docs]
    db.add(CareRevision(owner_id=user.id,changed_by_id=user.id,object_kind='topic',
        object_id=topic.id,from_version=topic.version,snapshot=snapshot,
        changed_fields=['deleted_at','group']))
    now = utcnow()
    topic.version += 1
    topic.deleted_at = now
    for event in events:
        await record_revision(db,user,'event',event,['deleted_at'])
        event.deleted_at = now
    for doc in docs:
        db.add(DocumentRevision(owner_id=user.id,changed_by_id=user.id,document_id=doc.id,
            from_version=doc.version,snapshot=document_json(doc),changed_fields=['deleted_at']))
        doc.version += 1
        doc.deleted_at = now
    return {'event_count':len(events),'document_count':len(docs)}


async def restore_group(db,user,topic):
    # The latest container lifecycle revision identifies the precise deletion.
    revision = await db.scalar(select(CareRevision).where(CareRevision.owner_id == user.id,
        CareRevision.object_kind == 'topic',CareRevision.object_id == topic.id)
        .order_by(CareRevision.from_version.desc()).limit(1))
    if not revision or 'group' not in revision.changed_fields:
        return
    for model,key in [(Encounter,'group_events'),(Document,'group_documents')]:
        for saved in revision.snapshot.get(key,[]):
            row = await db.scalar(select(model).where(model.id == UUID(saved['id']),
                model.owner_id == user.id).with_for_update())
            if row is None or row.version != saved['version'] or row.deleted_at is None:
                raise HTTPException(409,'整组资料在回收站中已被修改，请先核对后分别恢复')
            if model is Encounter:
                await record_revision(db,user,'event',row,['deleted_at'])
            else:
                db.add(DocumentRevision(owner_id=user.id,changed_by_id=user.id,document_id=row.id,
                    from_version=row.version,snapshot=document_json(row),changed_fields=['deleted_at']))
                row.version += 1
            row.deleted_at = None
