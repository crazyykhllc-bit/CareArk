"""Source-preserving projections for the care timeline.

Reading these projections never calls the vision model or changes stored records.
"""

from collections import Counter
from datetime import date, timezone
from uuid import UUID

from sqlalchemy import func, or_, select

from app.hospitals import hospital_key
from app.models import CareTopic, CareTopicEncounter, Document, Encounter, RelatedEncounter


EVENT_KIND_LABELS = {
    'outpatient': '门诊', 'inpatient': '住院', 'examination': '检查',
    'laboratory': '检验', 'checkup': '体检', 'procedure': '操作',
    'followup': '复诊', 'other': '其他诊疗',
}
DATE_BASIS_LABELS = {
    'visit': '就诊日期', 'admission': '入院日期', 'examination': '检查日期',
    'sampling': '采样日期', 'procedure': '操作日期', 'report': '报告日期',
    'user_confirmed': '已确认日期', 'unknown': '日期待核对',
}


def classify_document(document_type: str) -> str | None:
    if '发票' in document_type or '收费' in document_type or '药品' in document_type:
        return None
    if '处方' in document_type:
        return None
    if '挂号' in document_type or '就诊' in document_type or document_type == '门诊病历':
        return 'outpatient'
    if '检验' in document_type:
        return 'laboratory'
    if '检查' in document_type:
        return 'examination'
    if '体检' in document_type:
        return 'checkup'
    return None


def document_date_basis(document: Document) -> str:
    label = document.primary_date_raw or ''
    if '就诊' in label or '挂号' in label:
        return 'visit'
    if '入院' in label:
        return 'admission'
    if '采样' in label or '送检' in label:
        return 'sampling'
    if '检查' in label:
        return 'examination'
    # The primary date may be the report or review date. This conservative
    # label avoids claiming an admission or visit date from a report image.
    return 'report' if document.primary_date else 'unknown'


async def create_event_for_document(db, owner_id, document: Document) -> Encounter | None:
    kind = classify_document(document.document_type)
    if not kind or document.encounter_id:
        return None
    date_source = {'document_id': str(document.id), 'source_unit_id': None, 'page': None,
                   'field': 'document.primary_date', 'quote': document.primary_date_raw,
                   'document_version': document.version}
    event = Encounter(owner_id=owner_id, title=document.title, hospital=document.hospital,
        department=document.department, date=document.primary_date, date_basis=document_date_basis(document),
        date_sources=[date_source] if document.primary_date else [], event_kind=kind,
        evidence=[], summary_facts=derived_facts([document], 2), milestones=[])
    db.add(event)
    await db.flush()
    document.encounter_id = event.id
    return event


def safe_fact(document: Document, text: str, index: int) -> dict:
    return {
        'id': f'document-{document.id}-fact-{index}',
        'text': text[:1000], 'origin': 'source',
        'date': None, 'date_basis': None,
        'source_refs': [{
            'document_id': str(document.id), 'source_unit_id': None, 'page': None,
            'field': f'document.key_information.{index}', 'quote': text[:1000],
            'document_version': document.version,
        }],
    }


def derived_facts(documents: list[Document], maximum: int = 2) -> list[dict]:
    facts = []
    for document in sorted(documents, key=lambda x: (x.primary_date or date.min, x.created_at.replace(tzinfo=timezone.utc) if x.created_at and x.created_at.tzinfo is None else x.created_at), reverse=True):
        for index, value in enumerate(document.key_information or []):
            if isinstance(value, str) and value.strip():
                facts.append(safe_fact(document, value.strip(), index))
                if len(facts) == maximum:
                    return facts
    return facts


def event_json(event: Encounter, documents: list[Document], topic_ids: list[str] | None = None) -> dict:
    live_docs = {str(item.id): item for item in documents}
    stored = [fact for fact in (event.summary_facts or [])
              if fact.get('origin') == 'user_note' or any(
                  str(ref.get('document_id')) in live_docs and
                  (ref.get('document_version') is None or live_docs[str(ref.get('document_id'))].version == ref.get('document_version'))
                  for ref in fact.get('source_refs', []))]
    milestones = [fact for fact in (event.milestones or []) if fact.get('origin') == 'user_note' or any(
        str(ref.get('document_id')) in live_docs and
        (ref.get('document_version') is None or live_docs[str(ref.get('document_id'))].version == ref.get('document_version'))
        for ref in fact.get('source_refs', []))]
    stale_date = bool(event.date_sources) and any(
        str(ref.get('document_id')) not in live_docs or
        (ref.get('document_version') is not None and live_docs[str(ref.get('document_id'))].version != ref.get('document_version'))
        for ref in event.date_sources)
    kinds = Counter(item.document_type for item in documents)
    dates = sorted(item.primary_date for item in documents if item.primary_date)
    hospitals = sorted({name for name in [event.hospital, *(d.hospital for d in documents)] if name})
    return {
        'id': str(event.id), 'title': event.title, 'hospital': event.hospital,
        'hospitals': hospitals, 'hospital_count': len({hospital_key(name) for name in hospitals}),
        'department': event.department, 'date': event.date.isoformat() if event.date else None,
        'date_end': event.date_end.isoformat() if event.date_end else None,
        'date_basis': (event.date_basis or 'user_confirmed') if event.date else 'unknown',
        'date_basis_label': DATE_BASIS_LABELS.get((event.date_basis or 'user_confirmed') if event.date else 'unknown', '日期待核对'),
        'date_sources': event.date_sources or [], 'date_review_required': stale_date,
        'event_kind': event.event_kind or 'other',
        'event_kind_label': EVENT_KIND_LABELS.get(event.event_kind or 'other', '其他诊疗'),
        'document_count': len(documents), 'document_types': dict(kinds),
        'document_date_range': [dates[0].isoformat(), dates[-1].isoformat()] if dates else None,
        'facts': (stored or derived_facts(documents))[:2],
        'milestones': milestones, 'user_note': event.user_note,
        'topic_ids': topic_ids or [], 'primary_topic_id': str(event.primary_topic_id)
            if event.primary_topic_id and str(event.primary_topic_id) in (topic_ids or []) else None,
        'version': event.version,
        'deleted_at': event.deleted_at.isoformat() if event.deleted_at else None,
    }


async def event_documents(db, owner_id, event_ids: list[UUID]) -> dict:
    if not event_ids:
        return {}
    docs = (await db.scalars(select(Document).where(
        Document.owner_id == owner_id, Document.deleted_at.is_(None), Document.encounter_id.in_(event_ids)))).all()
    grouped = {event_id: [] for event_id in event_ids}
    for doc in docs:
        grouped.setdefault(doc.encounter_id, []).append(doc)
    return grouped


async def topic_memberships(db, owner_id, event_ids: list[UUID]) -> dict:
    if not event_ids:
        return {}
    rows = (await db.execute(select(CareTopicEncounter.encounter_id, CareTopicEncounter.topic_id)
        .join(CareTopic, CareTopic.id == CareTopicEncounter.topic_id)
        .where(CareTopicEncounter.owner_id == owner_id, CareTopic.owner_id == owner_id,
               CareTopic.deleted_at.is_(None), CareTopicEncounter.encounter_id.in_(event_ids)))).all()
    grouped = {}
    for encounter_id, topic_id in rows:
        grouped.setdefault(encounter_id, []).append(str(topic_id))
    return grouped


async def serialize_events(db, owner_id, events: list[Encounter]) -> list[dict]:
    ids = [item.id for item in events]
    docs = await event_documents(db, owner_id, ids)
    topics = await topic_memberships(db, owner_id, ids)
    return [event_json(event, docs.get(event.id, []), topics.get(event.id, [])) for event in events]


def event_filters(owner_id, *, query=None, hospital=None, event_kind=None, date_from=None, date_to=None,
                  topic_id=None, include_deleted=False):
    conditions = [Encounter.owner_id == owner_id]
    if not include_deleted:
        conditions.append(Encounter.deleted_at.is_(None))
    if query:
        term = f'%{query.strip()}%'
        conditions.append(or_(Encounter.title.ilike(term), Encounter.hospital.ilike(term), Encounter.department.ilike(term)))
    if hospital:
        conditions.append(Encounter.hospital == hospital)
    if event_kind:
        conditions.append(Encounter.event_kind == event_kind)
    if date_from:
        conditions.append(Encounter.date >= date_from)
    if date_to:
        conditions.append(Encounter.date <= date_to)
    if topic_id:
        conditions.append(Encounter.id.in_(select(CareTopicEncounter.encounter_id).where(
            CareTopicEncounter.owner_id == owner_id, CareTopicEncounter.topic_id == topic_id)))
    return conditions


async def event_detail(db, owner_id, event: Encounter) -> dict:
    from app.api.archive import document_json

    documents = (await db.scalars(select(Document).where(
        Document.owner_id == owner_id, Document.encounter_id == event.id, Document.deleted_at.is_(None))
        .order_by(Document.primary_date.desc(), Document.created_at.desc()))).all()
    memberships = await topic_memberships(db, owner_id, [event.id])
    related_ids = (await db.scalars(select(RelatedEncounter.document_id).where(
        RelatedEncounter.owner_id == owner_id, RelatedEncounter.encounter_id == event.id))).all()
    related_docs = (await db.scalars(select(Document).where(
        Document.owner_id == owner_id, Document.deleted_at.is_(None), Document.id.in_(related_ids)))).all() if related_ids else []
    outward = {doc.encounter_id for doc in related_docs if doc.encounter_id and doc.encounter_id != event.id}
    reverse = (await db.scalars(select(RelatedEncounter.encounter_id).join(Document,
        Document.id == RelatedEncounter.document_id).where(RelatedEncounter.owner_id == owner_id,
        Document.owner_id == owner_id, Document.deleted_at.is_(None), Document.encounter_id == event.id))).all()
    related_event_ids = outward | {item for item in reverse if item != event.id}
    related_events = (await db.scalars(select(Encounter).where(Encounter.owner_id == owner_id,
        Encounter.deleted_at.is_(None), Encounter.id.in_(related_event_ids)))).all() if related_event_ids else []
    result = event_json(event, documents, memberships.get(event.id, []))
    result['documents'] = [document_json(item) for item in documents]
    result['related_documents'] = [document_json(item) for item in related_docs]
    result['related_events'] = [{'id': str(item.id), 'title': item.title, 'hospital': item.hospital,
        'date': item.date.isoformat() if item.date else None} for item in related_events]
    result['facts'] = [fact for fact in (event.summary_facts or []) if fact.get('origin') == 'user_note' or any(
        str(ref.get('document_id')) in {str(doc.id) for doc in documents} and
        (ref.get('document_version') is None or next(doc.version for doc in documents if str(doc.id) == str(ref.get('document_id'))) == ref.get('document_version'))
        for ref in fact.get('source_refs', []))] or derived_facts(documents, 20)
    return result
