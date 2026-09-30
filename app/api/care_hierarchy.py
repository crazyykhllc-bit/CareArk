from collections import Counter
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_history import check_version, get_event
from app.care_schemas import VersionAction
from app.db import get_db
from app.dependencies import get_current_user
from app.models import CareTopic, CareTopicEncounter, CareSuggestion, Document, Encounter, User, utcnow
from app.schemas import StrictModel
from app.services.care_history import EVENT_KIND_LABELS, classify_document, document_date_basis, serialize_events
from app.services.care_hierarchy import (children, get_topic, hierarchy_cards, overview,
    record_revision, set_parent, topic_cards)

router = APIRouter(prefix='/api')


class Upgrade(VersionAction):
    name: str = Field(min_length=1,max_length=300)


class Parent(VersionAction):
    topic_id: UUID
    action: Literal['move','reference'] = 'move'


class AttachDocuments(StrictModel):
    document_ids: list[UUID] = Field(min_length=1,max_length=200)
    expected_version: int | None = Field(default=None,ge=1)


class EventVersion(VersionAction):
    id: UUID


class AttachEvents(StrictModel):
    events: list[EventVersion] = Field(min_length=1, max_length=200)
    action: Literal['move','reference'] = 'move'


class SplitDocuments(VersionAction):
    document_ids: list[UUID] = Field(min_length=1,max_length=200)
    title: str = Field(min_length=1,max_length=300)


def page(items, offset, limit):
    total = len(items)
    selected = items[offset:offset+limit]
    return {'items':selected,'total':total,'next_offset':offset+len(selected) if offset+len(selected)<total else None}


def ambiguous_events(owner_id):
    return select(Encounter.id).join(CareTopicEncounter,CareTopicEncounter.encounter_id == Encounter.id).join(
        CareTopic,CareTopic.id == CareTopicEncounter.topic_id).where(Encounter.owner_id == owner_id,
        Encounter.deleted_at.is_(None),Encounter.primary_topic_id.is_(None),
        CareTopicEncounter.owner_id == owner_id,CareTopic.owner_id == owner_id,
        CareTopic.deleted_at.is_(None)).group_by(Encounter.id).having(func.count(CareTopic.id)>1)


@router.get('/care-hierarchy/ownership-review')
async def ownership_review(offset: int = Query(0,ge=0),limit: int = Query(20,ge=1,le=100),
    user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    query = select(Encounter).where(Encounter.id.in_(ambiguous_events(user.id))).order_by(Encounter.id)
    total = await db.scalar(select(func.count()).select_from(ambiguous_events(user.id).subquery())) or 0
    events = list((await db.scalars(query.offset(offset).limit(limit))).all())
    return {'items':await serialize_events(db,user.id,events),'total':total,
        'next_offset':offset+len(events) if offset+len(events)<total else None}


@router.get('/care-hierarchy')
async def list_hierarchy(query: str | None = None, hospital: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
    kind: Literal['all','event','topic'] = 'all', event_kind: str | None = None,
    topic_id: UUID | None = None, month: str | None = None, older: bool = False,
    offset: int = Query(0,ge=0),limit: int = Query(10,ge=1,le=100),
    user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    cards = await hierarchy_cards(db,user.id)
    # Filter choices belong to the whole archive, not the current result set.
    all_hospitals = Counter(h for x in cards for h in
        (x.get('hospitals') or ([x['hospital']] if x.get('hospital') else [])))
    if topic_id:
        cards = [x for x in cards if x['item_type'] == 'topic' and x['id'] == str(topic_id)
            or str(topic_id) in x.get('topic_ids',[])]
    if kind != 'all':
        cards = [x for x in cards if x['item_type'] == kind]
    if event_kind:
        matching = set((await db.scalars(select(Encounter.primary_topic_id).where(
            Encounter.owner_id == user.id,Encounter.deleted_at.is_(None),Encounter.event_kind == event_kind))).all())
        kind_label = EVENT_KIND_LABELS.get(event_kind) if event_kind != 'other' else None
        cards = [x for x in cards if x.get('event_kind') == event_kind or
            x['item_type'] == 'topic' and (UUID(x['id']) in matching or
                bool(kind_label and kind_label in x.get('name','')))]
    if hospital:
        cards = [x for x in cards if x.get('hospital') == hospital or hospital in x.get('hospitals',[])]
    if query and query.strip():
        term = query.strip().casefold()
        cards = [x for x in cards if term in ' '.join(str(x.get(k) or '') for k in
            ('title','name','hospital','hospitals','department')).casefold()]
    if date_from:
        cards = [x for x in cards if x['date'] and x['date'] >= date_from.isoformat()]
    if date_to:
        cards = [x for x in cards if (x.get('date_start') or x['date']) and
            (x.get('date_start') or x['date']) <= date_to.isoformat()]
    tail = cards[10:]
    months = Counter(x['date'][:7] for x in tail if x['date'])
    hospitals = Counter(h for x in cards for h in (x.get('hospitals') or ([x['hospital']] if x.get('hospital') else [])))
    ownership_pending = await db.scalar(select(func.count()).select_from(ambiguous_events(user.id).subquery())) or 0
    metadata = {'older_months':[{'month':m,'count':count} for m,count in sorted(months.items(),reverse=True)],
        'undated_count':sum(x['date'] is None for x in tail),
        'hospitals':[{'name':h,'event_count':count} for h,count in sorted(all_hospitals.items())],
        'summary':{'event_count':len(cards),'hospital_count':len(hospitals),
            'latest_date':next((x['date'] for x in cards if x['date']),None),
            'pending_count':await db.scalar(select(func.count()).select_from(CareSuggestion).where(
                CareSuggestion.owner_id == user.id,CareSuggestion.status == 'pending')) or 0}}
    metadata['summary']['pending_count'] += ownership_pending
    if month and month != 'undated':
        try:
            if len(month) != 7 or date.fromisoformat(month+'-01').strftime('%Y-%m') != month:
                raise ValueError()
        except ValueError:
            raise HTTPException(422,'月份格式应为 YYYY-MM')
    if older or month:
        cards = tail
    if month:
        cards = [x for x in cards if (x['date'] is None if month == 'undated' else
            bool(x['date']) and x['date'][:7] == month)]
    return {**page(cards,offset,limit),**metadata}


@router.get('/care-hierarchy/search')
async def search(kind: Literal['event','document','topic'],query: str | None = None,
    encounter_id: UUID | None = None,
    offset: int = Query(0,ge=0),limit: int = Query(20,ge=1,le=100),
    user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    model = {'event':Encounter,'document':Document,'topic':CareTopic}[kind]
    conditions = [model.owner_id == user.id,model.deleted_at.is_(None)]
    if encounter_id and kind == 'document':
        conditions.append(Document.encounter_id == encounter_id)
    if query and query.strip():
        term = '%'+query.strip()+'%'
        fields = [model.name] if kind == 'topic' else [model.title,model.hospital]
        conditions.append(or_(*(field.ilike(term) for field in fields)))
    total = await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    rows = list((await db.scalars(select(model).where(*conditions)
        .order_by(model.created_at.desc(),model.id.desc()).offset(offset).limit(limit))).all())
    if kind == 'topic':
        items = await topic_cards(db,user.id,rows)
    else:
        if kind == 'event':
            items = await serialize_events(db,user.id,rows)
            event_map = {x.id:x for x in rows}
        else:
            from app.api.archive import document_json
            items = [document_json(x) for x in rows]
            event_ids = {x.encounter_id for x in rows if x.encounter_id}
            event_map = {x.id:x for x in (await db.scalars(select(Encounter).where(
                Encounter.id.in_(event_ids),Encounter.owner_id == user.id))).all()}
        parent_ids = {x.primary_topic_id for x in event_map.values() if x.primary_topic_id}
        parents = {x.id:x for x in (await db.scalars(select(CareTopic).where(CareTopic.id.in_(parent_ids),
            CareTopic.owner_id == user.id,CareTopic.deleted_at.is_(None)))).all()}
        for row,item in zip(rows,items):
            event = row if kind == 'event' else event_map.get(row.encounter_id)
            parent = parents.get(event.primary_topic_id) if event else None
            item.update({'item_type':kind,'primary_topic_id':str(parent.id) if parent else None,
                'primary_topic_name':parent.name if parent else None,
                'encounter_title':event.title if event else None})
    return {'items':items,'total':total,'next_offset':offset+len(rows) if offset+len(rows)<total else None}


@router.post('/care-history/events/{event_id}/upgrade')
async def upgrade(event_id: UUID,data: Upgrade,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    event = await get_event(db,user.id,event_id,lock=True)
    name = data.name.strip()
    if not name:
        raise HTTPException(422,'大事件名称不能为空')
    if event.primary_topic_id:
        existing = await db.scalar(select(CareTopic).where(CareTopic.id == event.primary_topic_id,
            CareTopic.owner_id == user.id).with_for_update())
        if existing and existing.deleted_at is None:
            existing = await get_topic(db,user.id,existing.id,active=True)
            if existing.name == name:
                return {'topic_id':str(existing.id),'event_id':str(event.id),'version':event.version,
                    'topic_version':existing.version}
            raise HTTPException(409,'此次诊疗已经属于大事件，请使用移动或相关引用')
    check_version(event,data.expected_version)
    topic = CareTopic(owner_id=user.id,name=name,status='active',origin='manual')
    db.add(topic); await db.flush()
    await set_parent(db,user,event,topic)
    await db.commit()
    return {'topic_id':str(topic.id),'event_id':str(event.id),'version':event.version,'topic_version':topic.version}


@router.put('/care-history/events/{event_id}/parent')
async def assign_parent(event_id: UUID,data: Parent,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    event = await get_event(db,user.id,event_id,lock=True)
    topic = await get_topic(db,user.id,data.topic_id,active=True)
    check_version(event,data.expected_version)
    await set_parent(db,user,event,topic,reference=data.action == 'reference')
    await db.commit()
    return {'event_id':str(event.id),'topic_id':str(topic.id),'primary_topic_id':str(event.primary_topic_id) if event.primary_topic_id else None,
        'version':event.version,'topic_version':topic.version}


@router.delete('/care-history/events/{event_id}/parent')
async def detach(event_id: UUID,expected_version: int = Query(...,ge=1),
    user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    event = await get_event(db,user.id,event_id,lock=True)
    check_version(event,expected_version)
    await set_parent(db,user,event,None)
    await db.commit()
    return {'event_id':str(event.id),'primary_topic_id':None,'version':event.version}


@router.post('/care-topics/{topic_id}/downgrade')
async def downgrade(topic_id: UUID,data: VersionAction,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    from app.models import UploadBatch, UploadCareContext
    topic = await get_topic(db,user.id,topic_id,active=True)
    check_version(topic,data.expected_version)
    child_ids = select(Encounter.id).where(Encounter.owner_id == user.id,
        Encounter.primary_topic_id == topic.id,Encounter.deleted_at.is_(None))
    pending = await db.scalar(select(UploadBatch.id).join(UploadCareContext,
        UploadBatch.care_context_id == UploadCareContext.id).where(
        UploadBatch.owner_id == user.id,UploadCareContext.owner_id == user.id,
        UploadBatch.status.not_in(['archived','cancelled']),or_(UploadCareContext.topic_id == topic.id,
        UploadCareContext.event_id.in_(child_ids))).limit(1))
    if not pending:
        child_set={str(x) for x in (await db.scalars(child_ids)).all()}
        drafts=(await db.scalars(select(UploadBatch).where(UploadBatch.owner_id == user.id,
            UploadBatch.status.not_in(['archived','cancelled'])))).all()
        pending=any(choice.get('topic_id') == str(topic.id) or choice.get('event_id') in child_set
            for batch in drafts for choice in (batch.grouping or {}).get('care_targets',{}).values())
    if pending:
        raise HTTPException(409,'大事件存在待确认上传，请先完成或调整上传任务')
    events = await children(db,user.id,topic.id)
    if len(events) != 1:
        raise HTTPException(422,'恢复为小事件需要恰好一次有效诊疗')
    event = await get_event(db,user.id,events[0].id,lock=True)
    await set_parent(db,user,event,None)
    await record_revision(db,user,'topic',topic,['deleted_at'])
    topic.deleted_at = utcnow()
    await db.commit()
    return {'topic_id':str(topic.id),'event_id':str(event.id),'version':topic.version,'event_version':event.version}


@router.post('/care-topics/{topic_id}/attach-documents')
async def attach_documents(topic_id: UUID,data: AttachDocuments,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    from app.services.care_attachment import attach_source_documents
    topic = await get_topic(db,user.id,topic_id,active=True)
    if data.expected_version is not None:
        check_version(topic,data.expected_version)
    events = await attach_source_documents(db,user,topic,data.document_ids)
    await db.commit()
    return {'topic_id':str(topic.id),'event_ids':[str(x) for x in events],'version':topic.version}


@router.post('/care-topics/{topic_id}/attach-events')
async def attach_events(topic_id: UUID,data: AttachEvents,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db,user.id,topic_id,active=True)
    events = {}
    for choice in sorted(data.events,key=lambda x:str(x.id)):
        event = await get_event(db,user.id,choice.id,lock=True)
        check_version(event,choice.expected_version)
        events[event.id] = event
    for event in events.values():
        await set_parent(db,user,event,topic,reference=data.action=='reference')
    await db.commit()
    return {'topic_id':str(topic.id),'event_ids':[str(x) for x in events],'version':topic.version}


@router.post('/care-history/events/{event_id}/split-documents')
async def split_documents(event_id: UUID,data: SplitDocuments,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    from app.api.archive import document_json
    from app.models import DocumentRevision
    event=await get_event(db,user.id,event_id,lock=True)
    check_version(event,data.expected_version)
    parent=None
    if event.primary_topic_id:
        parent=await db.scalar(select(CareTopic).where(CareTopic.id==event.primary_topic_id,
            CareTopic.owner_id==user.id,CareTopic.deleted_at.is_(None)))
        if parent:
            parent=await get_topic(db,user.id,parent.id,active=True)
    if not data.title.strip():
        raise HTTPException(422,'请填写新诊疗名称')
    ids=set(data.document_ids)
    docs=list((await db.scalars(select(Document).where(Document.owner_id == user.id,
        Document.encounter_id == event.id,Document.deleted_at.is_(None),Document.id.in_(ids))
        .order_by(Document.id).with_for_update())).all())
    if len(docs)!=len(ids):
        raise HTTPException(422,'只能拆出当前诊疗中的有效资料')
    first=min(docs,key=lambda x:(x.primary_date is None,x.primary_date or date.max,str(x.id)))
    new=Encounter(owner_id=user.id,title=data.title.strip(),hospital=first.hospital or event.hospital,
        department=first.department,date=first.primary_date,date_basis=document_date_basis(first),
        event_kind=classify_document(first.document_type) or event.event_kind,
        evidence=[f'split_from_event:{event.id}','user_care_mode:small'])
    db.add(new)
    await db.flush()
    await record_revision(db,user,'event',event,['documents'])
    for doc in docs:
        db.add(DocumentRevision(owner_id=user.id,changed_by_id=user.id,document_id=doc.id,
            from_version=doc.version,snapshot=document_json(doc),changed_fields=['encounter_id']))
        doc.version+=1
        doc.encounter_id=new.id
    if parent:
        await set_parent(db,user,new,parent)
    await db.commit()
    return {'event_id':str(new.id),'original_event_id':str(event.id),'version':event.version}


@router.get('/care-topics/{topic_id}/overview')
async def topic_overview(topic_id: UUID,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    topic = await get_topic(db,user.id,topic_id)
    return await overview(db,user.id,topic)


@router.post('/care-topics/{topic_id}/trash-group')
async def recycle_group(topic_id: UUID,data: VersionAction,user: User = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    from app.services.care_lifecycle import trash_group
    topic = await get_topic(db,user.id,topic_id)
    check_version(topic,data.expected_version)
    counts = await trash_group(db,user,topic)
    await db.commit()
    return {'id':str(topic.id),'version':topic.version,**counts}
