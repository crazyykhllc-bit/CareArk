from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.hospitals import hospital_key
from app.models import Encounter, Document, RelatedEncounter, User
from app.schemas import StrictModel

router = APIRouter(prefix='/api')


def encounter_json(row):
    return {'id': str(row.id), 'title': row.title, 'hospital': row.hospital,
            'date': row.date.isoformat() if row.date else None, 'patient_identity': row.patient_identity,
            'evidence': row.evidence, 'version': row.version}


@router.get('/encounters')
async def list_encounters(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Encounter).where(Encounter.owner_id == user.id,
        Encounter.deleted_at.is_(None)).order_by(Encounter.created_at.desc()).limit(500))).all()
    relations = (await db.scalars(select(RelatedEncounter).where(RelatedEncounter.owner_id == user.id))).all()
    related = {}
    for link in relations:
        related.setdefault(link.encounter_id, []).append(str(link.document_id))
    return {'items': [{**encounter_json(x), 'related_document_ids': related.get(x.id, [])} for x in rows]}


@router.get('/encounters/{encounter_id}')
async def get_encounter(encounter_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.api.archive import document_json
    row = await db.scalar(select(Encounter).where(Encounter.id == encounter_id, Encounter.owner_id == user.id,
        Encounter.deleted_at.is_(None)))
    if not row:
        raise HTTPException(404, '就诊记录不存在')
    docs = (await db.scalars(select(Document).where(Document.encounter_id == row.id, Document.owner_id == user.id,
                                                     Document.deleted_at.is_(None)))).all()
    related_ids = (await db.scalars(select(RelatedEncounter.document_id).where(
        RelatedEncounter.owner_id == user.id, RelatedEncounter.encounter_id == row.id))).all()
    return {**encounter_json(row), 'documents': [document_json(x) for x in docs],
            'related_document_ids': [str(x) for x in related_ids]}


class LinkEncounter(StrictModel):
    expected_version: int
    encounter_id: UUID | None = None


@router.patch('/documents/{document_id}/encounter')
async def link_encounter(document_id: UUID, data: LinkEncounter, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    document = await db.scalar(select(Document).where(Document.id == document_id, Document.owner_id == user.id,
                                                      Document.deleted_at.is_(None)).with_for_update())
    if not document:
        raise HTTPException(404, '资料不存在')
    if document.version != data.expected_version:
        raise HTTPException(409, '资料已更新，请刷新')
    if data.encounter_id:
        visit = await db.scalar(select(Encounter).where(Encounter.id == data.encounter_id, Encounter.owner_id == user.id,
            Encounter.deleted_at.is_(None)))
        if not visit:
            raise HTTPException(404, '就诊记录不存在')
        if hospital_key(document.hospital) and hospital_key(visit.hospital) and hospital_key(document.hospital) != hospital_key(visit.hospital):
            raise HTTPException(422, '这是不同医院的就诊；请使用“相关诊疗”关联，保留各自就诊记录')
    document.encounter_id = data.encounter_id
    if data.encounter_id:
        redundant = await db.scalar(select(RelatedEncounter).where(RelatedEncounter.owner_id == user.id,
            RelatedEncounter.document_id == document.id, RelatedEncounter.encounter_id == data.encounter_id))
        if redundant:
            await db.delete(redundant)
    document.version += 1
    await db.commit()
    return {'version': document.version, 'encounter_id': str(document.encounter_id) if document.encounter_id else None}


@router.put('/documents/{document_id}/related-encounters/{encounter_id}')
async def add_related_encounter(document_id: UUID, encounter_id: UUID,
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    document = await db.scalar(select(Document).where(Document.id == document_id, Document.owner_id == user.id,
                                                      Document.deleted_at.is_(None)))
    visit = await db.scalar(select(Encounter).where(Encounter.id == encounter_id, Encounter.owner_id == user.id,
        Encounter.deleted_at.is_(None)))
    if not document or not visit:
        raise HTTPException(404, '资料或就诊记录不存在')
    if document.encounter_id == visit.id:
        raise HTTPException(422, '该资料已属于这次就诊，无需重复关联')
    existing = await db.scalar(select(RelatedEncounter).where(RelatedEncounter.owner_id == user.id,
        RelatedEncounter.document_id == document.id, RelatedEncounter.encounter_id == visit.id))
    if not existing:
        db.add(RelatedEncounter(owner_id=user.id, document_id=document.id, encounter_id=visit.id))
        from app.services.care_topics import organize_topics
        await organize_topics(db, user.id)
        await db.commit()
    return {'document_id': str(document.id), 'encounter_id': str(visit.id)}


@router.delete('/documents/{document_id}/related-encounters/{encounter_id}')
async def remove_related_encounter(document_id: UUID, encounter_id: UUID,
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    link = await db.scalar(select(RelatedEncounter).where(RelatedEncounter.owner_id == user.id,
        RelatedEncounter.document_id == document_id, RelatedEncounter.encounter_id == encounter_id))
    if not link:
        raise HTTPException(404, '相关诊疗关联不存在')
    await db.delete(link)
    from app.services.care_topics import organize_topics
    await organize_topics(db, user.id)
    await db.commit()
    return {'removed': True}
