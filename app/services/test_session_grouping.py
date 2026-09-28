import re
import unicodedata
from collections import defaultdict

from sqlalchemy import select

from app.hospitals import hospital_key
from app.models import Document, LabResult, TestSession, TestSessionSource


_DYNAMIC_KEYWORDS = ('ogtt', '糖耐', '葡萄糖耐量', '胰岛素释放', 'c肽释放')


def _canonical(value):
    return re.sub(r'[\s_\-（）()]+', '', unicodedata.normalize('NFKC', value or '').casefold())


def _context(document, lab):
    observed = lab.observed_date or document.primary_date
    return observed, hospital_key(document.hospital)


def _has_keyword(document):
    text = _canonical(' '.join(filter(None, [document.title, document.document_type, document.parsed_content])))
    return any(keyword in text for keyword in _DYNAMIC_KEYWORDS)


def _conflicts(rows):
    values = defaultdict(set)
    for lab, _document in rows:
        key = (_canonical(lab.analyte_key or lab.name), _canonical(lab.unit), lab.timepoint_minutes)
        if lab.result is not None:
            values[key].add(_canonical(lab.result))
    return any(len(items) > 1 for items in values.values())


def _suggestion_key(rows):
    lab, document = rows[0]
    observed, hospital = _context(document, lab)
    return f'{observed.isoformat() if observed else "undated"}:{hospital or "unknown"}'


async def _create_session(db, owner_id, rows):
    first_lab, first_document = rows[0]
    observed, _ = _context(first_document, first_lab)
    title = 'OGTT' if any(_has_keyword(document) for _lab, document in rows) else '动态检验'
    session = TestSession(owner_id=owner_id, name=f'{title} · {observed.isoformat()}' if observed else title,
                          session_date=observed, hospital=first_document.hospital)
    db.add(session)
    await db.flush()
    source_ids = set()
    for lab, _document in rows:
        lab.test_session_id = session.id
        if lab.source_unit_id:
            source_ids.add(lab.source_unit_id)
    db.add_all(TestSessionSource(owner_id=owner_id, test_session_id=session.id, source_unit_id=source_id)
               for source_id in source_ids)
    return session


async def group_confirmed_test_results(db, owner_id, document_ids):
    """Group unambiguous time-point labs and report suggestions without guessing from date alone."""
    document_ids = set(document_ids)
    rows = (await db.execute(
        select(LabResult, Document).join(Document, Document.id == LabResult.document_id).where(
            LabResult.owner_id == owner_id,
            Document.owner_id == owner_id, Document.deleted_at.is_(None),
            Document.patient_scope == 'self',
            LabResult.review_status == 'confirmed',
            LabResult.timepoint_minutes.is_not(None),
            LabResult.test_session_id.is_(None),
        )
    )).all()
    rows = list(rows)
    used = set()
    candidates = []

    explicit = defaultdict(list)
    for row in rows:
        if row[0].test_session_key:
            explicit[_canonical(row[0].test_session_key)].append(row)
    for group in explicit.values():
        if any(document.id in document_ids for _lab, document in group):
            candidates.append(('strong', group))
            used.update(lab.id for lab, _document in group)

    by_document = defaultdict(list)
    for row in rows:
        if row[0].id not in used:
            by_document[row[1].id].append(row)
    for document_id, group in by_document.items():
        if document_id in document_ids and (len({lab.timepoint_minutes for lab, _document in group}) >= 2 or
                                             _has_keyword(group[0][1])):
            candidates.append(('strong', group))
            used.update(lab.id for lab, _document in group)

    by_context = defaultdict(list)
    for row in rows:
        if row[0].id not in used:
            by_context[_context(row[1], row[0])].append(row)
    for group in by_context.values():
        if not any(document.id in document_ids for _lab, document in group) or len(group) < 2:
            continue
        if any(_has_keyword(document) for _lab, document in group) and len({lab.timepoint_minutes for lab, _ in group}) >= 2:
            candidates.append(('strong', group))
        else:
            candidates.append(('suggested', group))
        used.update(lab.id for lab, _document in group)

    decisions = []
    for confidence, group in candidates:
        documents = sorted({str(document.id) for _lab, document in group})
        labs = sorted(str(lab.id) for lab, _document in group)
        if _conflicts(group):
            decisions.append({'status': 'separate', 'reason': 'conflicting_duplicate_timepoint',
                              'document_ids': documents, 'lab_result_ids': labs})
        elif confidence == 'strong':
            session = await _create_session(db, owner_id, group)
            decisions.append({'status': 'automatic', 'reason': 'strong_dynamic_test_evidence',
                              'session_id': str(session.id), 'document_ids': documents, 'lab_result_ids': labs})
        else:
            decisions.append({'status': 'suggested', 'reason': 'same_context_needs_confirmation',
                              'suggestion_key': _suggestion_key(group),
                              'document_ids': documents, 'lab_result_ids': labs})
    return decisions


async def candidate_metadata(db, owner_id):
    rows = (await db.execute(
        select(LabResult, Document).join(Document, Document.id == LabResult.document_id).where(
            LabResult.owner_id == owner_id, Document.owner_id == owner_id,
            Document.deleted_at.is_(None),
            Document.patient_scope == 'self', LabResult.review_status == 'confirmed',
            LabResult.test_session_id.is_(None), LabResult.timepoint_minutes.is_not(None),
        )
    )).all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[_context(row[1], row[0])].append(row)
    metadata = {}
    for group in grouped.values():
        conflict = _conflicts(group)
        suggestion = _suggestion_key(group) if len(group) > 1 and not conflict else None
        for lab, _document in group:
            metadata[lab.id] = {
                'suggestion_key': suggestion,
                'suggestion_reason': '同日同医院的多时间点资料，关联证据需要确认' if suggestion else None,
                'conflict_reason': '同一项目和时间点存在冲突结果' if conflict else None,
            }
    return metadata
