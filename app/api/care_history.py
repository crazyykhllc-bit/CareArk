from collections import Counter
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.care_schemas import EventCreate, EventUpdate, TopicCreate, TopicUpdate, VersionAction, SuggestionAccept
from app.db import get_db
from app.dependencies import get_current_user
from app.hospitals import hospital_key
from app.models import CareRevision, CareSuggestion, CareTopic, CareTopicEncounter, CareTopicExclusion, Document, DocumentSource, SourceUnit, Encounter, User, utcnow
from app.services.care_history import event_detail, event_filters, serialize_events
from app.services.care_suggestions import accept_suggestion
from app.services.care_topics import organize_topics
from app.services.topic_analysis import analyze_existing_topic
from app.services.extraction import ExtractionError

router = APIRouter(prefix='/api')


def topic_json(topic, *, event_count=0, hospital_count=0, latest_date=None):
    return {'id': str(topic.id), 'name': topic.name, 'note': topic.note, 'status': topic.status,
            'origin': topic.origin,
            'event_count': event_count, 'hospital_count': hospital_count,
            'latest_date': latest_date.isoformat() if latest_date else None,
            'version': topic.version, 'deleted_at': topic.deleted_at.isoformat() if topic.deleted_at else None}


def snapshot_event(event):
    return {'title': event.title, 'hospital': event.hospital, 'department': event.department,
            'primary_topic_id': str(event.primary_topic_id) if event.primary_topic_id else None,
            'event_kind': event.event_kind, 'date': event.date.isoformat() if event.date else None,
            'date_end': event.date_end.isoformat() if event.date_end else None, 'date_basis': event.date_basis,
            'date_sources': event.date_sources or [], 'summary_facts': event.summary_facts or [],
            'milestones': event.milestones or [], 'user_note': event.user_note,
            'deleted_at': event.deleted_at.isoformat() if event.deleted_at else None}


def snapshot_topic(topic):
    return {'name': topic.name, 'note': topic.note, 'status': topic.status,
            'deleted_at': topic.deleted_at.isoformat() if topic.deleted_at else None}


async def get_event(db, owner_id, event_id, *, allow_deleted=False, lock=False):
    statement = select(Encounter).where(Encounter.id == event_id, Encounter.owner_id == owner_id)
    if not allow_deleted:
        statement = statement.where(Encounter.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    event = await db.scalar(statement)
    if not event:
        raise HTTPException(404, '诊疗事件不存在')
    return event


async def get_topic(db, owner_id, topic_id, *, allow_deleted=False, lock=False):
    statement = select(CareTopic).where(CareTopic.id == topic_id, CareTopic.owner_id == owner_id)
    if not allow_deleted:
        statement = statement.where(CareTopic.deleted_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    topic = await db.scalar(statement)
    if not topic:
        raise HTTPException(404, '诊疗主题不存在')
    return topic


def check_version(row, expected):
    if row.version != expected:
        raise HTTPException(409, '内容已更新，请刷新后再保存')


async def revision(db, user, kind, row, fields):
    db.add(CareRevision(owner_id=user.id, object_kind=kind, object_id=row.id,
                        from_version=row.version, snapshot=snapshot_event(row) if kind == 'event' else snapshot_topic(row),
                        changed_fields=fields, changed_by_id=user.id))
    row.version += 1


async def validate_facts(db, owner_id, event_id, facts):
    for fact in facts or []:
        for ref in fact.source_refs:
            document = await db.scalar(select(Document).where(Document.id == ref.document_id,
                Document.owner_id == owner_id, Document.encounter_id == event_id, Document.deleted_at.is_(None)))
            if not document:
                raise HTTPException(422, {'field': 'source_refs', 'message': '事项来源必须是本次诊疗的有效资料'})
            if ref.document_version is not None and document.version != ref.document_version:
                raise HTTPException(409, '来源资料已更新，请重新核对事项')
            if ref.source_unit_id:
                source = await db.scalar(select(SourceUnit).join(DocumentSource,
                    DocumentSource.source_unit_id == SourceUnit.id).where(SourceUnit.id == ref.source_unit_id,
                    SourceUnit.owner_id == owner_id, DocumentSource.owner_id == owner_id,
                    DocumentSource.document_id == document.id))
                if not source:
                    raise HTTPException(422, {'field': 'source_unit_id', 'message': '来源页不属于这份资料'})
                if ref.page and source.page_index is not None and ref.page != source.page_index + 1:
                    raise HTTPException(422, {'field': 'page', 'message': '页码与来源不一致'})
            elif ref.page:
                raise HTTPException(422, {'field': 'page', 'message': '填写页码时必须选择来源页'})


@router.get('/care-history')
async def care_history(query: str | None = None, hospital: str | None = None, event_kind: str | None = None,
                       topic_id: UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conditions = event_filters(user.id, query=query, hospital=hospital, event_kind=event_kind,
                               topic_id=topic_id, date_from=date_from, date_to=date_to)
    count = await db.scalar(select(func.count()).select_from(Encounter).where(*conditions)) or 0
    hospitals = (await db.scalars(select(Encounter.hospital).where(*conditions, Encounter.hospital.is_not(None)).distinct())).all()
    latest = await db.scalar(select(func.max(Encounter.date)).where(*conditions))
    recent = (await db.scalars(select(Encounter).where(*conditions, Encounter.date.is_not(None))
        .order_by(Encounter.date.desc(), Encounter.id.desc()).limit(10))).all()
    recent_ids = [item.id for item in recent]
    older_dates = (await db.scalars(select(Encounter.date).where(*conditions, Encounter.date.is_not(None),
        Encounter.id.not_in(recent_ids) if recent_ids else True))).all()
    older_months = Counter(value.strftime('%Y-%m') for value in older_dates)
    undated = await db.scalar(select(func.count()).select_from(Encounter).where(*conditions, Encounter.date.is_(None))) or 0
    pending = await db.scalar(select(func.count()).select_from(CareSuggestion).where(
        CareSuggestion.owner_id == user.id, CareSuggestion.status == 'pending')) or 0
    return {'summary': {'event_count': count, 'hospital_count': len(hospitals),
                        'latest_date': latest.isoformat() if latest else None,
                        'undated_count': undated, 'pending_count': pending},
            'recent': await serialize_events(db, user.id, recent),
            'older_months': [{'month': month, 'count': number} for month, number in sorted(older_months.items(), reverse=True)],
            'hospitals': sorted(hospitals)}


@router.get('/care-history/events')
async def list_events(query: str | None = None, hospital: str | None = None, event_kind: str | None = None,
                      topic_id: UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                      month: str | None = None, undated: bool = False, deleted: bool = False, older: bool = False,
                      offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=20),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conditions = event_filters(user.id, query=query, hospital=hospital, event_kind=event_kind,
        topic_id=topic_id, date_from=date_from, date_to=date_to, include_deleted=True)
    conditions.append(Encounter.deleted_at.is_not(None) if deleted else Encounter.deleted_at.is_(None))
    if older:
        recent_conditions = event_filters(user.id, query=query, hospital=hospital, event_kind=event_kind,
            topic_id=topic_id, date_from=date_from, date_to=date_to)
        recent_ids = (await db.scalars(select(Encounter.id).where(*recent_conditions,
            Encounter.date.is_not(None)).order_by(Encounter.date.desc(), Encounter.id.desc()).limit(10))).all()
        if recent_ids:
            conditions.append(Encounter.id.not_in(recent_ids))
    if month:
        if len(month) != 7 or month[4] != '-' or not month[:4].isdigit() or not month[5:].isdigit() or not 1 <= int(month[5:]) <= 12:
            raise HTTPException(422, '月份格式应为 YYYY-MM')
        year, number = map(int, month.split('-'))
        start = date(year, number, 1)
        end = date(year + (number == 12), 1 if number == 12 else number + 1, 1)
        conditions.extend([Encounter.date >= start, Encounter.date < end])
    if undated:
        conditions.append(Encounter.date.is_(None))
    count = await db.scalar(select(func.count()).select_from(Encounter).where(*conditions)) or 0
    rows = (await db.scalars(select(Encounter).where(*conditions)
        .order_by(Encounter.date.desc(), Encounter.id.desc()).offset(offset).limit(limit))).all()
    return {'items': await serialize_events(db, user.id, rows), 'total': count,
            'next_offset': offset + len(rows) if offset + len(rows) < count else None}


@router.get('/care-history/events/{event_id}')
async def read_event(event_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await event_detail(db, user.id, await get_event(db, user.id, event_id))


@router.post('/care-history/events', status_code=201)
async def create_event(data: EventCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if data.date_end and data.date and data.date_end < data.date:
        raise HTTPException(422, {'field': 'date_end', 'message': '结束日期不能早于开始日期'})
    if data.document_ids:
        docs = (await db.scalars(select(Document).where(Document.id.in_(data.document_ids),
            Document.owner_id == user.id, Document.deleted_at.is_(None)).with_for_update())).all()
        if len(docs) != len(set(data.document_ids)):
            raise HTTPException(422, '选定资料不存在或不属于当前账号')
        if any(doc.encounter_id is not None for doc in docs):
            raise HTTPException(422, '选定资料已经属于另一诊疗事件')
        member_hospitals = {hospital_key(doc.hospital) for doc in docs if hospital_key(doc.hospital)}
        if len(member_hospitals) > 1:
            raise HTTPException(422, {'field': 'document_ids', 'message': '不同医院的资料不能作为同一次诊疗；可在诊疗主题中关联'})
        if any(hospital_key(doc.hospital) and hospital_key(data.hospital) and hospital_key(doc.hospital) != hospital_key(data.hospital) for doc in docs):
            raise HTTPException(422, '不同医院的资料请建立相关诊疗关联')
    else:
        docs = []
    event_hospital = data.hospital or next((doc.hospital for doc in docs if doc.hospital), None)
    event = Encounter(owner_id=user.id, title=data.title, hospital=event_hospital, department=data.department,
        event_kind=data.event_kind, date=data.date, date_end=data.date_end,
        date_basis=data.date_basis if data.date else 'unknown',
        user_note=data.user_note, evidence=[], date_sources=[], summary_facts=[], milestones=[])
    db.add(event)
    await db.flush()
    for doc in docs:
        doc.encounter_id = event.id
        doc.version += 1
    await organize_topics(db, user.id)
    await db.commit()
    return await event_detail(db, user.id, event)


@router.patch('/care-history/events/{event_id}')
async def update_event(event_id: UUID, data: EventUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    event = await get_event(db, user.id, event_id, lock=True)
    check_version(event, data.expected_version)
    fields = data.model_fields_set - {'expected_version'}
    if not fields:
        return await event_detail(db, user.id, event)
    if any(name in fields and getattr(data, name) is None for name in ('title','event_kind','date_basis')):
        raise HTTPException(422, '标题、类型和日期含义不能为空')
    proposed_date = data.date if 'date' in fields else event.date
    proposed_end = data.date_end if 'date_end' in fields else event.date_end
    if proposed_end and proposed_date and proposed_end < proposed_date:
        raise HTTPException(422, {'field': 'date_end', 'message': '结束日期不能早于开始日期'})
    if 'hospital' in fields and data.hospital:
        member_hospitals = (await db.scalars(select(Document.hospital).where(Document.owner_id == user.id,
            Document.encounter_id == event.id, Document.deleted_at.is_(None), Document.hospital.is_not(None)))).all()
        if any(hospital_key(value) and hospital_key(value) != hospital_key(data.hospital) for value in member_hospitals):
            raise HTTPException(422, {'field': 'hospital', 'message': '事件医院与已有资料不一致'})
    for name in ('summary_facts', 'milestones'):
        if name in fields:
            await validate_facts(db, user.id, event.id, getattr(data, name))
    await revision(db, user, 'event', event, sorted(fields))
    for name in fields:
        value = getattr(data, name)
        if name in ('summary_facts', 'milestones'):
            value = [item.model_dump(mode='json') for item in value or []]
        setattr(event, name, value)
    if 'date' in fields and 'date_basis' not in fields:
        event.date_basis = 'user_confirmed' if event.date else 'unknown'
    if 'date' in fields:
        event.date_sources = []
        if event.date is None:
            event.date_basis = 'unknown'
    await organize_topics(db, user.id)
    await db.commit()
    return await event_detail(db, user.id, event)


@router.post('/care-history/events/{event_id}/trash')
@router.post('/care-history/events/{event_id}/restore')
async def toggle_event(event_id: UUID, data: VersionAction, request: Request,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    event = await get_event(db, user.id, event_id, allow_deleted=True, lock=True)
    check_version(event, data.expected_version)
    restoring = request.url.path.endswith('/restore')
    desired = None if restoring else utcnow()
    if bool(event.deleted_at) != restoring:
        return {'id': str(event.id), 'version': event.version,
                'deleted_at': event.deleted_at.isoformat() if event.deleted_at else None}
    await revision(db, user, 'event', event, ['deleted_at'])
    event.deleted_at = desired
    await db.commit()
    return {'id': str(event.id), 'version': event.version, 'deleted_at': desired.isoformat() if desired else None}


@router.get('/care-history/events/{event_id}/revisions')
async def event_revisions(event_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_event(db, user.id, event_id, allow_deleted=True)
    rows = (await db.scalars(select(CareRevision).where(CareRevision.owner_id == user.id,
        CareRevision.object_kind == 'event', CareRevision.object_id == event_id)
        .order_by(CareRevision.created_at.desc()))).all()
    return {'items': [{'from_version': row.from_version, 'snapshot': row.snapshot,
                       'changed_fields': row.changed_fields, 'created_at': row.created_at.isoformat()} for row in rows]}


@router.get('/care-topics')
async def list_topics(include_archived: bool = True, deleted: bool = False,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conditions = [CareTopic.owner_id == user.id, CareTopic.deleted_at.is_not(None) if deleted else CareTopic.deleted_at.is_(None)]
    if not include_archived:
        conditions.append(CareTopic.status == 'active')
    topics = (await db.scalars(select(CareTopic).where(*conditions).order_by(CareTopic.updated_at.desc()))).all()
    if not topics:
        return {'items': []}
    associations = (await db.execute(select(CareTopicEncounter.topic_id, Encounter.id, Encounter.hospital, Encounter.date)
        .join(Encounter, Encounter.id == CareTopicEncounter.encounter_id)
        .where(CareTopicEncounter.owner_id == user.id, Encounter.owner_id == user.id,
               Encounter.deleted_at.is_(None), CareTopicEncounter.topic_id.in_([topic.id for topic in topics])))).all()
    by_topic = {}
    for topic_id, event_id, hospital, event_date in associations:
        by_topic.setdefault(topic_id, []).append((event_id, hospital, event_date))
    return {'items': [topic_json(topic, event_count=len(by_topic.get(topic.id, [])),
        hospital_count=len({hospital_key(x[1]) for x in by_topic.get(topic.id, []) if x[1]}),
        latest_date=max((x[2] for x in by_topic.get(topic.id, []) if x[2]), default=None)) for topic in topics]}


@router.post('/care-topics/organize')
async def organize_care_topics(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await organize_topics(db, user.id)
    await db.commit()
    return result


@router.post('/care-topics', status_code=201)
async def create_topic(data: TopicCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.care_attachment import attach_source_documents
    event_ids = set(data.event_ids)
    if event_ids:
        found = set((await db.scalars(select(Encounter.id).where(Encounter.owner_id == user.id,
            Encounter.deleted_at.is_(None), Encounter.id.in_(event_ids)))).all())
        if found != event_ids:
            raise HTTPException(422, '主题中包含不存在或其他账号的诊疗事件')
    topic = CareTopic(owner_id=user.id, name=data.name.strip(), note=data.note, status='active')
    db.add(topic)
    await db.flush()
    for event_id in event_ids:
        db.add(CareTopicEncounter(owner_id=user.id, topic_id=topic.id, encounter_id=event_id))
        event = await get_event(db, user.id, event_id, lock=True)
        if event.primary_topic_id is None:
            await revision(db, user, 'event', event, ['primary_topic_id'])
            event.primary_topic_id = topic.id
    await attach_source_documents(db, user, topic, data.document_ids)
    await organize_topics(db, user.id)
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(CareTopicEncounter).where(
        CareTopicEncounter.topic_id == topic.id, CareTopicEncounter.owner_id == user.id)) or 0
    return topic_json(topic, event_count=count)


@router.get('/care-topics/{topic_id}')
async def read_topic(topic_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db, user.id, topic_id)
    events = (await db.scalars(select(Encounter).join(CareTopicEncounter,
        CareTopicEncounter.encounter_id == Encounter.id).where(CareTopicEncounter.topic_id == topic.id,
        CareTopicEncounter.owner_id == user.id, Encounter.owner_id == user.id, Encounter.deleted_at.is_(None))
        .order_by(Encounter.date.is_(None), Encounter.date.asc(), Encounter.id.asc()))).all()
    return {**topic_json(topic, event_count=len(events)), 'events': await serialize_events(db, user.id, events)}


@router.post('/care-topics/{topic_id}/analyze')
async def analyze_care_topic(topic_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db, user.id, topic_id)
    try:
        result = await analyze_existing_topic(db, user.id, topic)
    except ExtractionError as error:
        raise HTTPException(503, str(error)) from error
    await db.commit()
    return result


@router.patch('/care-topics/{topic_id}')
async def update_topic(topic_id: UUID, data: TopicUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db, user.id, topic_id, lock=True)
    check_version(topic, data.expected_version)
    fields = data.model_fields_set - {'expected_version'}
    if 'name' in fields and (data.name is None or not data.name.strip()):
        raise HTTPException(422, '主题名称不能为空')
    if fields:
        await revision(db, user, 'topic', topic, sorted(fields))
        for field in fields:
            setattr(topic, field, getattr(data, field))
        if topic.status == 'active':
            await organize_topics(db, user.id)
        await db.commit()
    return topic_json(topic)


@router.put('/care-topics/{topic_id}/events/{event_id}')
async def add_topic_event(topic_id: UUID, event_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db, user.id, topic_id)
    await get_event(db, user.id, event_id)
    link = await db.scalar(select(CareTopicEncounter).where(CareTopicEncounter.owner_id == user.id,
        CareTopicEncounter.topic_id == topic.id, CareTopicEncounter.encounter_id == event_id))
    if not link:
        exclusion = await db.scalar(select(CareTopicExclusion).where(CareTopicExclusion.owner_id == user.id,
            CareTopicExclusion.topic_id == topic.id, CareTopicExclusion.encounter_id == event_id))
        if exclusion:
            await db.delete(exclusion)
        db.add(CareTopicEncounter(owner_id=user.id, topic_id=topic.id, encounter_id=event_id))
        await revision(db, user, 'topic', topic, ['events'])
        await db.commit()
    return {'topic_id': str(topic.id), 'event_id': str(event_id), 'version': topic.version}


@router.delete('/care-topics/{topic_id}/events/{event_id}')
async def remove_topic_event(topic_id: UUID, event_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db, user.id, topic_id)
    link = await db.scalar(select(CareTopicEncounter).where(CareTopicEncounter.owner_id == user.id,
        CareTopicEncounter.topic_id == topic.id, CareTopicEncounter.encounter_id == event_id))
    if link:
        await revision(db, user, 'topic', topic, ['events'])
        event = await get_event(db, user.id, event_id, allow_deleted=True, lock=True)
        if event.primary_topic_id == topic.id:
            await revision(db, user, 'event', event, ['primary_topic_id'])
            event.primary_topic_id = None
        await db.delete(link)
        exclusion = await db.scalar(select(CareTopicExclusion).where(CareTopicExclusion.owner_id == user.id,
            CareTopicExclusion.topic_id == topic.id, CareTopicExclusion.encounter_id == event_id))
        if not exclusion:
            db.add(CareTopicExclusion(owner_id=user.id, topic_id=topic.id, encounter_id=event_id))
        await db.commit()
    return {'removed': bool(link), 'version': topic.version}


@router.post('/care-topics/{topic_id}/trash')
@router.post('/care-topics/{topic_id}/restore')
async def toggle_topic(topic_id: UUID, data: VersionAction, request: Request,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db, user.id, topic_id, allow_deleted=True, lock=True)
    check_version(topic, data.expected_version)
    restoring = request.url.path.endswith('/restore')
    if bool(topic.deleted_at) != restoring:
        return topic_json(topic)
    if restoring:
        from app.services.care_lifecycle import restore_group
        await restore_group(db,user,topic)
    await revision(db, user, 'topic', topic, ['deleted_at'])
    topic.deleted_at = None if restoring else utcnow()
    await db.commit()
    return topic_json(topic)


@router.get('/care-topics/{topic_id}/revisions')
async def topic_revisions(topic_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_topic(db, user.id, topic_id, allow_deleted=True)
    rows = (await db.scalars(select(CareRevision).where(CareRevision.owner_id == user.id,
        CareRevision.object_kind == 'topic', CareRevision.object_id == topic_id)
        .order_by(CareRevision.created_at.desc()))).all()
    return {'items': [{'from_version': row.from_version, 'snapshot': row.snapshot,
                       'changed_fields': row.changed_fields, 'created_at': row.created_at.isoformat()} for row in rows]}


@router.get('/care-suggestions')
async def list_suggestions(status: str = 'pending', offset: int = Query(default=0, ge=0),
                           limit: int = Query(default=20, ge=1, le=20),
                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conditions = [CareSuggestion.owner_id == user.id, CareSuggestion.status == status]
    total = await db.scalar(select(func.count()).select_from(CareSuggestion).where(*conditions)) or 0
    rows = (await db.scalars(select(CareSuggestion).where(*conditions)
        .order_by(CareSuggestion.created_at.desc(), CareSuggestion.id.desc()).offset(offset).limit(limit))).all()
    return {'items': [{'id': str(row.id), 'kind': row.kind, 'payload': row.payload,
                       'status': row.status, 'version': row.version} for row in rows],
            'total': total, 'next_offset': offset + len(rows) if offset + len(rows) < total else None}


@router.post('/care-suggestions/{suggestion_id}/accept')
async def accept_organization(suggestion_id: UUID, data: SuggestionAccept,
                              user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    suggestion = await db.scalar(select(CareSuggestion).where(CareSuggestion.id == suggestion_id,
        CareSuggestion.owner_id == user.id).with_for_update())
    if not suggestion:
        raise HTTPException(404, '整理建议不存在')
    check_version(suggestion, data.expected_version)
    return await accept_suggestion(db, user, suggestion, title=data.title,
        date=data.date, date_provided='date' in data.model_fields_set, date_basis=data.date_basis)


@router.post('/care-suggestions/{suggestion_id}/dismiss')
async def dismiss_organization(suggestion_id: UUID, data: VersionAction,
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    suggestion = await db.scalar(select(CareSuggestion).where(CareSuggestion.id == suggestion_id,
        CareSuggestion.owner_id == user.id).with_for_update())
    if not suggestion:
        raise HTTPException(404, '整理建议不存在')
    check_version(suggestion, data.expected_version)
    if suggestion.status != 'pending':
        raise HTTPException(409, '这项建议已处理')
    suggestion.status = 'dismissed'
    suggestion.version += 1
    await db.commit()
    return {'id': str(suggestion.id), 'status': suggestion.status, 'version': suggestion.version}
