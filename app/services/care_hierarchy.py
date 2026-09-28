"""Explicit care ownership, independent from automatic related-topic suggestions."""
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.hospitals import hospital_key
from app.models import (CareRevision, CareTopic, CareTopicEncounter, CareTopicExclusion,
    Document, Encounter, LabResult, MetricDefinition)
from app.services.care_history import event_documents, serialize_events


async def get_topic(db, owner_id, topic_id, *, active=False):
    topic = await db.scalar(select(CareTopic).where(CareTopic.id == topic_id,
        CareTopic.owner_id == owner_id, CareTopic.deleted_at.is_(None)).with_for_update())
    if topic is None:
        raise HTTPException(404, '大事件不存在')
    if active and topic.status != 'active':
        raise HTTPException(409, '大事件已归档，请先恢复为进行中')
    return topic


async def record_revision(db, user, kind, row, fields):
    from app.api.care_history import snapshot_event, snapshot_topic
    snapshot = snapshot_event(row) if kind == 'event' else snapshot_topic(row)
    if kind == 'event':
        snapshot['primary_topic_id'] = str(row.primary_topic_id) if row.primary_topic_id else None
    db.add(CareRevision(owner_id=user.id, changed_by_id=user.id, object_kind=kind,
        object_id=row.id, from_version=row.version, snapshot=snapshot, changed_fields=fields))
    row.version += 1


async def membership(db, owner_id, event_id, topic_id, *, remove=False):
    link = await db.scalar(select(CareTopicEncounter).where(CareTopicEncounter.owner_id == owner_id,
        CareTopicEncounter.encounter_id == event_id, CareTopicEncounter.topic_id == topic_id))
    exclusion = await db.scalar(select(CareTopicExclusion).where(CareTopicExclusion.owner_id == owner_id,
        CareTopicExclusion.encounter_id == event_id, CareTopicExclusion.topic_id == topic_id))
    if remove:
        if link:
            await db.delete(link)
        if not exclusion:
            db.add(CareTopicExclusion(owner_id=owner_id, encounter_id=event_id, topic_id=topic_id))
    else:
        if exclusion:
            await db.delete(exclusion)
        if link:
            link.origin = 'manual'
        else:
            db.add(CareTopicEncounter(owner_id=owner_id, encounter_id=event_id, topic_id=topic_id, origin='manual'))


async def set_parent(db, user, event, topic, *, reference=False):
    """Keep sources and encounter identity unchanged; only an explicit user sets ownership."""
    destination = topic.id if topic else None
    if reference:
        present = await db.scalar(select(CareTopicEncounter.id).where(
            CareTopicEncounter.owner_id == user.id, CareTopicEncounter.topic_id == destination,
            CareTopicEncounter.encounter_id == event.id))
        if not present:
            await record_revision(db, user, 'event', event, ['topic_references'])
            await record_revision(db, user, 'topic', topic, ['event_references'])
            await membership(db, user.id, event.id, destination)
        return
    if event.primary_topic_id == destination:
        return
    await record_revision(db, user, 'event', event, ['primary_topic_id'])
    previous = event.primary_topic_id
    if previous:
        old = await db.scalar(select(CareTopic).where(CareTopic.id == previous,
            CareTopic.owner_id == user.id).with_for_update())
        if old:
            await record_revision(db, user, 'topic', old, ['events'])
        await membership(db, user.id, event.id, previous, remove=True)
    event.primary_topic_id = destination
    if topic:
        await membership(db, user.id, event.id, destination)
        await record_revision(db, user, 'topic', topic, ['events'])


async def children(db, owner_id, topic_id):
    return list((await db.scalars(select(Encounter).where(Encounter.owner_id == owner_id,
        Encounter.deleted_at.is_(None), Encounter.primary_topic_id == topic_id)
        .order_by(Encounter.date.is_(None), Encounter.date.desc(), Encounter.id.desc()))).all())


async def topic_cards(db, owner_id, topics, events=None, documents=None):
    from app.api.care_history import topic_json
    if events is None:
        events = list((await db.scalars(select(Encounter).where(Encounter.owner_id == owner_id,
            Encounter.deleted_at.is_(None), Encounter.primary_topic_id.in_([x.id for x in topics])))).all())
    if documents is None:
        documents = await event_documents(db, owner_id, [x.id for x in events])
    grouped = defaultdict(list)
    for event in events:
        grouped[event.primary_topic_id].append(event)
    result = []
    for topic in topics:
        members = grouped[topic.id]
        dates = [x.date for x in members if x.date]
        ends = [x.date_end or x.date for x in members if x.date_end or x.date]
        raw_hospitals = {name for event in members for name in
            [event.hospital, *(doc.hospital for doc in documents.get(event.id, []))] if name}
        hospitals = {hospital_key(name) for name in raw_hospitals}
        result.append({**topic_json(topic, event_count=len(members),hospital_count=len(hospitals),
            latest_date=max(ends,default=None)), 'item_type':'topic', 'title':topic.name,
            'date':max(ends).isoformat() if ends else None,
            'date_start':min(dates).isoformat() if dates else None,
            'date_end':max(ends).isoformat() if ends else None,
            'document_count':sum(len(documents.get(x.id,[])) for x in members),
            'hospital':next((x.hospital for x in members if x.hospital),None) if len(hospitals) == 1 else None,
            'hospitals': sorted(raw_hospitals),
            'undated_event_count':sum(x.date is None for x in members)})
    return result


async def hierarchy_cards(db, owner_id):
    topics = list((await db.scalars(select(CareTopic).where(CareTopic.owner_id == owner_id,
        CareTopic.deleted_at.is_(None)))).all())
    events = list((await db.scalars(select(Encounter).where(Encounter.owner_id == owner_id,
        Encounter.deleted_at.is_(None)))).all())
    docs = await event_documents(db, owner_id, [x.id for x in events])
    live_topics = {x.id for x in topics}
    independent = [x for x in events if x.primary_topic_id not in live_topics]
    cards = [{**x,'item_type':'event','event_count':1,
        'status':'active'} for x in await serialize_events(db,owner_id,independent)]
    cards.extend(await topic_cards(db,owner_id,topics,events,docs))
    return sorted(cards,key=lambda x:(x['date'] or '',x['id']),reverse=True)


async def overview(db, owner_id, topic):
    from app.api.archive import document_json
    from app.api.costs import receipt_rows, effective_amount, is_excluded
    from app.currency import canonical_currency
    from app.services.metric_queries import query_metric_results
    events = await children(db,owner_id,topic.id)
    grouped = await event_documents(db,owner_id,[x.id for x in events])
    documents = [doc for event in events for doc in grouped.get(event.id,[])]
    document_ids = {x.id for x in documents}
    source_ids = {str(document_id) for document_id in document_ids}
    card = (await topic_cards(db,owner_id,[topic],events,grouped))[0]
    buckets = defaultdict(lambda:{'total':Decimal('0'),'known_count':0,'unknown_count':0})
    for document,receipt in await receipt_rows(db,owner_id):
        if document.id not in document_ids or is_excluded(receipt):
            continue
        bucket = buckets[canonical_currency(receipt.currency) if receipt else 'CNY']
        amount = effective_amount(document,receipt)
        bucket['known_count' if amount is not None else 'unknown_count'] += 1
        if amount is not None:
            bucket['total'] += amount
    metrics = list((await db.scalars(select(MetricDefinition).where(MetricDefinition.owner_id == owner_id))).all())
    lab_rows = (await db.execute(select(LabResult, Document).join(Document,
        Document.id == LabResult.document_id).where(
        LabResult.owner_id == owner_id, Document.owner_id == owner_id,
        Document.deleted_at.is_(None), Document.id.in_(document_ids)))).all() if document_ids else []
    summaries = []
    for metric in metrics:
        results = await query_metric_results(db,owner_id,metric,lab_rows=lab_rows,include_manual=False)
        matched = [x for x in results['items'] if x['source_type'] == 'lab_report' and
            x['source_id'] in source_ids]
        if not matched:
            continue
        latest = matched[0]
        summaries.append({'metric_id':str(metric.id),'name':metric.name,'unit':metric.unit,
            'result_count':len(matched),'latest':{'result':latest['raw_value'],'unit':latest['unit'],
                'date':latest['record_date'], 'document_id':latest['source_id'],'lab_result_id':latest['id']}})
    references = list((await db.scalars(select(Encounter).join(CareTopicEncounter,
        CareTopicEncounter.encounter_id == Encounter.id).where(
            CareTopicEncounter.owner_id == owner_id,CareTopicEncounter.topic_id == topic.id,
            Encounter.owner_id == owner_id,Encounter.deleted_at.is_(None),
            (Encounter.primary_topic_id.is_(None) | (Encounter.primary_topic_id != topic.id)))
        .order_by(Encounter.date.desc(),Encounter.id.desc()))).all())
    return {**card,'events':await serialize_events(db,owner_id,events),
        'related_events':await serialize_events(db,owner_id,references),
        'documents':[document_json(x) for x in documents], 'metric_summaries':summaries,
        'costs_by_currency':[{'currency':currency,**value,'total':f"{value['total']:.2f}"}
            for currency,value in sorted(buckets.items())]}
