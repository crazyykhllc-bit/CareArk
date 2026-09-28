"""Conservative, source-backed organization of related care events.

This never merges encounters or moves their source documents. A user can remove
an inferred membership, and that explicit decision is not recreated later.
"""

import re
from collections import defaultdict
from uuid import UUID

from sqlalchemy import select

from app.models import (CareTopic, CareTopicEncounter, CareTopicExclusion,
                        Document, Encounter, RelatedEncounter, User)


GENERIC_ENDINGS = re.compile(r'(?:的)?(?:手术|治疗|诊疗|复查|随访|检查|住院|门诊|报告|资料|主题)+$')
UNINFORMATIVE = {'医院', '就诊', '检查', '检验', '治疗', '住院', '手术', '复查', '随访', '健康'}
HISTORICAL_MARKERS = ('既往', '病史', '曾于', '曾经', '术后复查')


def topic_anchor(name: str) -> str | None:
    anchor = GENERIC_ENDINGS.sub('', re.sub(r'\s+', '', name or '').strip(' ·：:、'))
    if len(anchor) < 2 or anchor in UNINFORMATIVE or len(anchor) > 20 or '医院' in anchor:
        return None
    return anchor


def matching_source(topic: CareTopic, event: Encounter, documents: list[Document]) -> dict | None:
    anchor = topic_anchor(topic.name)
    if not anchor:
        return None
    if documents and anchor in event.title:
        return {'reason': 'event_title', 'anchor': anchor}
    for doc in documents:
        if doc.patient_scope == 'other':
            continue
        if anchor in doc.title:
            return {'reason': 'document_title', 'anchor': anchor, 'document_id': str(doc.id)}
        # An exact full topic phrase in a checked fact is stronger than a
        # condition mentioned incidentally in a different report's history.
        for fact in doc.key_information or []:
            if isinstance(fact, str) and topic.name in fact and not any(marker in fact for marker in HISTORICAL_MARKERS):
                return {'reason': 'document_fact', 'anchor': topic.name, 'document_id': str(doc.id)}
    return None


async def organize_topics(db, owner_id) -> dict:
    """Link clear matches and create a topic for explicit cross-event links."""
    events = (await db.scalars(select(Encounter).where(
        Encounter.owner_id == owner_id, Encounter.deleted_at.is_(None)))).all()
    all_topics = (await db.scalars(select(CareTopic).where(CareTopic.owner_id == owner_id))).all()
    topics = [topic for topic in all_topics if topic.deleted_at is None and topic.status == 'active']
    if not events:
        return {'created_topics': 0, 'linked_events': 0}
    event_by_id = {event.id: event for event in events}
    docs = (await db.scalars(select(Document).where(
        Document.owner_id == owner_id, Document.deleted_at.is_(None),
        Document.encounter_id.in_(event_by_id)))).all()
    docs_by_event = defaultdict(list)
    for doc in docs:
        docs_by_event[doc.encounter_id].append(doc)
    doc_by_id = {doc.id: doc for doc in docs}
    allowed = {event.id for event in events if not docs_by_event[event.id] or
               any(doc.patient_scope != 'other' for doc in docs_by_event[event.id])}
    memberships = (await db.scalars(select(CareTopicEncounter).where(
        CareTopicEncounter.owner_id == owner_id))).all()
    linked = {(row.topic_id, row.encounter_id) for row in memberships}
    exclusions = set((await db.execute(select(CareTopicExclusion.topic_id,
        CareTopicExclusion.encounter_id).where(CareTopicExclusion.owner_id == owner_id))).all())
    added = 0

    def attach(topic, event_id, evidence):
        nonlocal added
        pair = (topic.id, event_id)
        if event_id not in allowed or pair in linked or pair in exclusions:
            return
        db.add(CareTopicEncounter(owner_id=owner_id, topic_id=topic.id,
            encounter_id=event_id, origin='auto', evidence=evidence))
        linked.add(pair)
        added += 1

    for topic in topics:
        for event in events:
            evidence = matching_source(topic, event, docs_by_event[event.id])
            if evidence:
                attach(topic, event.id, evidence)

    # A related-encounter link is an explicit, reviewable source relationship.
    # It can connect hospitals inside a topic without merging their visits.
    relations = (await db.execute(select(RelatedEncounter, Document).join(
        Document, Document.id == RelatedEncounter.document_id).where(
        RelatedEncounter.owner_id == owner_id, Document.owner_id == owner_id,
        Document.deleted_at.is_(None), Document.encounter_id.is_not(None),
        Document.encounter_id != RelatedEncounter.encounter_id))).all()
    graph = defaultdict(set)
    evidence_by_edge = {}
    for relation, doc in relations:
        a, b = doc.encounter_id, relation.encounter_id
        if a not in allowed or b not in allowed or doc.patient_scope == 'other':
            continue
        graph[a].add(b)
        graph[b].add(a)
        evidence_by_edge[frozenset((a, b))] = str(doc.id)
    active_topics = {topic.id: topic for topic in topics}
    for row in memberships:
        if row.origin != 'auto' or row.topic_id not in active_topics:
            continue
        event = event_by_id.get(row.encounter_id)
        topic = active_topics[row.topic_id]
        directly_supported = bool(event and matching_source(topic, event, docs_by_event[event.id]))
        if row.evidence and row.evidence.get('reason') == 'model_source_quote':
            source_id = row.evidence.get('document_id')
            source = doc_by_id.get(UUID(source_id)) if source_id else None
            quote = row.evidence.get('quote') or ''
            source_text = '\n'.join([source.title, *(part for part in source.key_information or []
                if isinstance(part, str)), source.parsed_content or '']) if source else ''
            directly_supported = bool(source and source.encounter_id == row.encounter_id and
                source.version == row.evidence.get('document_version') and
                topic.name == row.evidence.get('topic_name') and quote and quote in source_text)
        related_in_topic = any((topic.id, neighbor) in linked for neighbor in graph[row.encounter_id])
        if not directly_supported and not related_in_topic:
            if event and event.primary_topic_id == topic.id:
                from app.services.care_hierarchy import record_revision
                user = await db.get(User, owner_id)
                await record_revision(db, user, 'event', event, ['primary_topic_id'])
                event.primary_topic_id = None
            await db.delete(row)
            linked.discard((row.topic_id, row.encounter_id))
    created = 0
    seen = set()
    for start in graph:
        if start in seen:
            continue
        component, queue = set(), [start]
        while queue:
            current = queue.pop()
            if current in component:
                continue
            component.add(current)
            queue.extend(graph[current] - component)
        seen.update(component)
        if len(component) < 2:
            continue
        existing = next((topic for topic in topics if any((topic.id, item) in linked for item in component)), None)
        if existing:
            targets = [existing]
        else:
            # Explicit upload choices always take precedence over inferred groups.
            if any(event_by_id[item].primary_topic_id or any(
                isinstance(marker,str) and marker.startswith('user_care_mode:')
                for marker in event_by_id[item].evidence or []) for item in component):
                continue
            # Do not recreate a topic the user archived, trashed, or emptied
            # by explicitly removing all of its inferred memberships.
            if any((topic.id, item) in linked for topic in all_topics for item in component) or any(
                pair[1] in component for pair in exclusions):
                continue
            first = sorted((event_by_id[item] for item in component),
                key=lambda event: (event.date is None, event.date, str(event.id)))[0]
            label = first.date.isoformat() if first.date else '日期待核对'
            existing = CareTopic(owner_id=owner_id, name=f'相关诊疗 · {label}',
                note='根据已确认的跨次诊疗关联自动整理；可修改名称或移除关联。',
                status='active', origin='auto')
            db.add(existing)
            await db.flush()
            from app.services.care_hierarchy import record_revision
            user = await db.get(User, owner_id)
            for event_id in sorted(component, key=str):
                event = event_by_id[event_id]
                await record_revision(db, user, 'event', event, ['primary_topic_id'])
                event.primary_topic_id = existing.id
            topics.append(existing)
            targets = [existing]
            created += 1
        for topic in targets:
            for event_id in component:
                source_id = next((evidence_by_edge[frozenset((event_id, neighbor))]
                    for neighbor in graph[event_id] if neighbor in component), None)
                attach(topic, event_id, {'reason': 'confirmed_relation', 'document_id': source_id})
    return {'created_topics': created, 'linked_events': added}
