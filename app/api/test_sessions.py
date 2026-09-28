import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Document, LabResult, SourceUnit, TestSession, TestSessionSource, User
from app.services.metric_matching import parse_strict_number
from app.test_session_schemas import TestSessionCreate, TestSessionUpdate


router = APIRouter(prefix='/api/test-sessions')


@router.get('/candidates')
async def list_candidates(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.test_session_grouping import candidate_metadata
    metadata = await candidate_metadata(db, user.id)
    rows = (await db.execute(select(LabResult, Document).join(Document, Document.id == LabResult.document_id)
        .where(LabResult.owner_id == user.id, Document.owner_id == user.id,
               Document.deleted_at.is_(None),
               LabResult.test_session_id.is_(None), LabResult.timepoint_minutes.is_not(None))
        .order_by(LabResult.observed_date.desc(), Document.primary_date.desc(), LabResult.created_at))).all()
    return {'items': [{
        'id': str(lab.id), 'document_id': str(document.id), 'document_title': document.title,
        'name': lab.name, 'analyte_key': lab.analyte_key, 'raw_value': lab.result, 'unit': lab.unit,
        'timepoint_minutes': lab.timepoint_minutes,
        'observed_date': (lab.observed_date or document.primary_date).isoformat()
                         if (lab.observed_date or document.primary_date) else None,
        'hospital': document.hospital,
        **metadata.get(lab.id, {'suggestion_key': None, 'suggestion_reason': None, 'conflict_reason': None}),
    } for lab, document in rows]}


async def session_json(db, row):
    labs = (await db.scalars(select(LabResult).where(LabResult.owner_id == row.owner_id,
        LabResult.test_session_id == row.id).order_by(LabResult.timepoint_minutes, LabResult.created_at))).all()
    sources = (await db.scalars(select(TestSessionSource.source_unit_id).where(
        TestSessionSource.owner_id == row.owner_id, TestSessionSource.test_session_id == row.id))).all()
    points = []
    for lab in labs:
        parsed = parse_strict_number(lab.result)
        points.append({'lab_result_id': str(lab.id), 'analyte_key': lab.analyte_key, 'name': lab.name,
                       'timepoint_minutes': lab.timepoint_minutes, 'raw_value': lab.result,
                       'value': str(parsed) if parsed is not None else None, 'unit': lab.unit,
                       'document_id': str(lab.document_id),
                       'source_unit_id': str(lab.source_unit_id) if lab.source_unit_id else None})
    return {'id': str(row.id), 'name': row.name,
            'session_date': row.session_date.isoformat() if row.session_date else None,
            'hospital': row.hospital, 'notes': row.notes, 'version': row.version,
            'source_unit_ids': [str(x) for x in sources], 'points': points}


async def validate_links(db, owner_id, lab_ids, source_ids, current_session_id=None):
    unique_labs = set(lab_ids)
    labs = list((await db.scalars(select(LabResult).where(LabResult.owner_id == owner_id,
                                                          LabResult.id.in_(unique_labs)))).all()) if unique_labs else []
    if len(labs) != len(unique_labs):
        raise HTTPException(422, '包含不存在或不属于当前用户的检验结果')
    if any(lab.test_session_id and lab.test_session_id != current_session_id for lab in labs):
        raise HTTPException(409, '检验结果已经属于另一项试验')
    unique_sources = set(source_ids)
    sources = list((await db.scalars(select(SourceUnit).where(SourceUnit.owner_id == owner_id,
                                                               SourceUnit.id.in_(unique_sources)))).all()) if unique_sources else []
    if len(sources) != len(unique_sources):
        raise HTTPException(422, '包含不存在或不属于当前用户的来源')
    return labs, sources


@router.get('')
async def list_sessions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(TestSession).where(TestSession.owner_id == user.id)
        .order_by(TestSession.session_date.desc(), TestSession.created_at.desc()))).all()
    return {'items': [await session_json(db, row) for row in rows]}


@router.post('', status_code=201)
async def create_session(data: TestSessionCreate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    labs, sources = await validate_links(db, user.id, data.lab_result_ids, data.source_unit_ids)
    row = TestSession(owner_id=user.id, name=data.name.strip(), session_date=data.session_date,
                      hospital=data.hospital.strip() if data.hospital else None, notes=data.notes)
    db.add(row)
    await db.flush()
    for lab in labs:
        lab.test_session_id = row.id
    db.add_all([TestSessionSource(owner_id=user.id, test_session_id=row.id, source_unit_id=source.id)
                for source in sources])
    await db.commit()
    return await session_json(db, row)


@router.put('/{session_id}')
async def update_session(session_id: uuid.UUID, data: TestSessionUpdate,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(TestSession).where(TestSession.id == session_id,
        TestSession.owner_id == user.id).with_for_update())
    if not row:
        raise HTTPException(404, '试验不存在')
    if row.version != data.expected_version:
        raise HTTPException(409, '试验已更新，请刷新')
    labs, sources = await validate_links(db, user.id, data.lab_result_ids, data.source_unit_ids, row.id)
    old_labs = (await db.scalars(select(LabResult).where(LabResult.owner_id == user.id,
                                                        LabResult.test_session_id == row.id))).all()
    for lab in old_labs:
        lab.test_session_id = None
    for lab in labs:
        lab.test_session_id = row.id
    old_sources = (await db.scalars(select(TestSessionSource).where(TestSessionSource.owner_id == user.id,
        TestSessionSource.test_session_id == row.id))).all()
    old_by_id = {source.source_unit_id: source for source in old_sources}
    requested_ids = {source.id for source in sources}
    for source_id, link in old_by_id.items():
        if source_id not in requested_ids:
            await db.delete(link)
    db.add_all([TestSessionSource(owner_id=user.id, test_session_id=row.id, source_unit_id=source.id)
                for source in sources if source.id not in old_by_id])
    row.name = data.name.strip(); row.session_date = data.session_date
    row.hospital = data.hospital.strip() if data.hospital else None; row.notes = data.notes
    row.version += 1
    await db.commit()
    return await session_json(db, row)
