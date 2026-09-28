"""User upload intent, separate from model output and source grouping."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.batch_schemas import CareTarget
from app.models import CareTopic, Encounter, UploadCareContext
from app.services.care_hierarchy import get_topic, set_parent, record_revision


def context_json(context):
    if context is None:
        return {'mode':'small', 'name':None, 'topic_id':None, 'event_id':None}
    return {'id':str(context.id), 'intent_key':context.intent_key, 'mode':context.mode, 'name':context.name,
            'topic_id':str(context.topic_id) if context.topic_id else None,
            'event_id':str(context.event_id) if context.event_id and context.mode != 'small' else None}


async def validate_target(db, owner_id, target):
    if target.mode == 'existing_topic' or (target.mode == 'new_topic' and target.topic_id):
        return await get_topic(db, owner_id, target.topic_id, active=True)
    if target.mode == 'existing_event':
        event = await db.scalar(select(Encounter).where(Encounter.id == target.event_id,
            Encounter.owner_id == owner_id, Encounter.deleted_at.is_(None)).with_for_update())
        if not event:
            raise HTTPException(404, '小事件不存在')
        if event.primary_topic_id:
            parent = await db.scalar(select(CareTopic).where(CareTopic.id == event.primary_topic_id,
                CareTopic.owner_id == owner_id, CareTopic.deleted_at.is_(None)).with_for_update())
            if parent and parent.status != 'active':
                raise HTTPException(409, '大事件已归档，请先恢复为进行中')
        return event
    return None


async def create_context(db, owner_id, intent):
    if intent is None:
        return None
    # Never accept a generated new parent's ID from a client.
    if intent.mode == 'new_topic' and intent.topic_id:
        raise HTTPException(422, '新建大事件不能指定已有目标')
    await validate_target(db, owner_id, intent)
    context = await db.scalar(select(UploadCareContext).where(UploadCareContext.owner_id == owner_id,
        UploadCareContext.intent_key == intent.intent_key).with_for_update())
    if context is None:
        try:
            async with db.begin_nested():
                context = UploadCareContext(owner_id=owner_id, **intent.model_dump())
                db.add(context)
                await db.flush()
        except IntegrityError:
            context = await db.scalar(select(UploadCareContext).where(UploadCareContext.owner_id == owner_id,
                UploadCareContext.intent_key == intent.intent_key).with_for_update())
    fields = ['mode', 'name'] + ([] if intent.mode == 'small' else ['event_id']) + ([] if intent.mode == 'new_topic' else ['topic_id'])
    if not context or any(getattr(context, key) != getattr(intent, key) for key in fields):
        raise HTTPException(409, '同一上传意图的归属已经确定，请完成本次上传后另建任务')
    return context


async def batch_context(db, owner_id, batch, *, lock=False):
    if not batch.care_context_id:
        return None
    query = select(UploadCareContext).where(UploadCareContext.id == batch.care_context_id,
        UploadCareContext.owner_id == owner_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    context = await db.scalar(query)
    if context is None:
        raise HTTPException(404, '上传归属不存在')
    return context


def group_target(batch, context, group_id):
    override = (batch.grouping or {}).get('care_targets', {}).get(group_id)
    return CareTarget.model_validate(override) if override else context or CareTarget()


async def parent_for_target(db, user, target, context):
    if target.mode == 'existing_topic':
        return await get_topic(db, user.id, target.topic_id, active=True)
    if target.mode != 'new_topic':
        return None
    if target is not context:
        raise HTTPException(422, '资料组请选择已有大事件，或使用本次上传的新建大事件')
    if context.topic_id:
        return await get_topic(db, user.id, context.topic_id, active=True)
    topic = CareTopic(owner_id=user.id, name=(context.name or '待命名大事件').strip() or '待命名大事件', origin='manual')
    db.add(topic)
    await db.flush()
    context.topic_id = topic.id
    return topic


async def bind_document(db, user, batch, context, group, document, revised_events, small_events):
    target = group_target(batch, context, group.id)
    if target.mode == 'archive':
        document.encounter_id = None
        return None
    if group.kind == 'medication' and not group.encounter_id:
        return None
    if target.mode == 'existing_event':
        event = await validate_target(db, user.id, target)
        if event.id not in revised_events:
            await record_revision(db, user, 'event', event, ['documents'])
            revised_events.add(event.id)
        marker = 'user_care_mode:existing_event'
        if marker not in (event.evidence or []):
            event.evidence = [*(event.evidence or []), marker]
        document.encounter_id = event.id
        return event
    explicit_small = target.mode == 'small' and (context is target or
        (batch.grouping or {}).get('care_targets', {}).get(group.id))
    small_key = ('context', str(context.id)) if target is context and context else ('override',target.name or '')
    if explicit_small:
        event = small_events.get(small_key)
        if event is None and target is context and context.event_id:
            event = await validate_target(db, user.id, CareTarget(mode='existing_event',event_id=context.event_id))
            if event.id not in revised_events:
                await record_revision(db, user, 'event', event, ['documents'])
                revised_events.add(event.id)
        if event is None:
            suggested = next((v for v in (batch.payload or {}).get('encounters', []) if v['id'] == group.encounter_id), None)
            if suggested:
                from datetime import date
                event = Encounter(owner_id=user.id, title=target.name or suggested['title'],
                    hospital=suggested.get('hospital'), date=date.fromisoformat(suggested['date']) if suggested.get('date') else None,
                    date_end=date.fromisoformat(suggested['date_end']) if suggested.get('date_end') else None,
                    patient_identity=suggested.get('patient_identity'),
                    date_basis=suggested.get('date_basis','unknown'), event_kind=suggested.get('event_kind','other'),
                    evidence=suggested.get('evidence',[]), department=suggested.get('department'))
                db.add(event)
                await db.flush()
        if event:
            document.encounter_id = event.id
            small_events[small_key] = event
    if document.encounter_id:
        event = await db.get(Encounter, document.encounter_id)
    else:
        from app.services.care_history import create_event_for_document
        event = await create_event_for_document(db, user.id, document)
        if event is None:
            event = Encounter(owner_id=user.id, title=target.name or document.title, hospital=document.hospital,
                              date=document.primary_date, date_basis='report' if document.primary_date else 'unknown')
            db.add(event)
            await db.flush()
            document.encounter_id = event.id
    if explicit_small:
        small_events[small_key] = event
        if target is context:
            context.event_id = event.id
    if target.mode == 'small' and target.name:
        event.title = target.name
    if target.mode == 'small' and (context or (batch.grouping or {}).get('care_targets', {}).get(group.id)):
        marker = 'user_care_mode:small'
        if marker not in (event.evidence or []):
            event.evidence = [*(event.evidence or []), marker]
    topic = await parent_for_target(db, user, target, context)
    if event.primary_topic_id and (not topic or event.primary_topic_id != topic.id):
        previous = await db.scalar(select(CareTopic).where(CareTopic.id == event.primary_topic_id,
            CareTopic.owner_id == user.id, CareTopic.deleted_at.is_(None)).with_for_update())
        if previous:
            raise HTTPException(409, '已有诊疗属于另一大事件，请先明确移出或移动归属，再补充上传')
    if topic:
        await set_parent(db, user, event, topic)
    return event
