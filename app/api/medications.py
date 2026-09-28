from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Document, Medication, MedicationEvent, MedicationSource, MedicationPackage, MedicationRevision, User
from app.schemas import MedicationEventInput, StrictModel
from app.services.medications import append_event, medication_json

router = APIRouter(prefix="/api/medications")


@router.get("")
async def list_medications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.scalars(select(Medication).where(Medication.owner_id == user.id,
        Medication.deleted_at.is_(None)).order_by(Medication.updated_at.desc()))).all()
    packages = (await db.scalars(select(MedicationPackage).where(MedicationPackage.owner_id == user.id))).all()
    sources = (await db.scalars(select(MedicationSource).where(MedicationSource.owner_id == user.id))).all()
    active_ids = set((await db.scalars(select(Document.id).where(Document.owner_id == user.id,
        Document.deleted_at.is_(None)))).all())
    by_medication = {row.id: [source for source in sources if source.medication_id == row.id] for row in rows}
    return {"items": [{**medication_json(row), 'packages': [package_json(p) for p in packages if p.medication_id == row.id and p.document_id in active_ids],
                       'sources': [{'document_id': str(s.document_id)} for s in by_medication[row.id] if s.document_id in active_ids]}
                      for row in rows if not by_medication[row.id] or any(s.document_id in active_ids for s in by_medication[row.id])]}


def package_json(p):
    return {'id': str(p.id), 'document_id': str(p.document_id), 'batch_number': p.batch_number,
            'expiry_date': p.expiry_date.isoformat() if p.expiry_date else None, 'quantity_raw': p.quantity_raw}


class MedicationUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=300)
    generic_name: str | None = Field(default=None, max_length=300)
    brand_name: str | None = Field(default=None, max_length=300)
    strength: str | None = Field(default=None, max_length=200)
    dosage_form: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=300)
    approval_number: str | None = Field(default=None, max_length=200)
    quantity: str | None = Field(default=None, max_length=100)
    route: str | None = Field(default=None, max_length=100)
    dose_each_time: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    timing: str | None = Field(default=None, max_length=200)
    planned_end_date: date | None = None

    @field_validator('name')
    @classmethod
    def name_required(cls, value):
        if value is None or not value.strip():
            raise ValueError('药品名称不能为空')
        return value.strip()


class MedicationLifecycleUpdate(StrictModel):
    expected_version: int = Field(ge=1)


@router.get('/trash')
async def list_trashed_medications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Medication).where(Medication.owner_id == user.id,
        Medication.deleted_at.is_not(None)).order_by(Medication.deleted_at.desc()))).all()
    return {'items': [medication_json(row) for row in rows]}


async def locked_medication(db, owner_id, medication_id, version):
    row = await db.scalar(select(Medication).where(Medication.id == medication_id,
        Medication.owner_id == owner_id).with_for_update())
    if not row:
        raise HTTPException(404, '药品不存在')
    if row.version != version:
        raise HTTPException(409, '药品资料已更新，请刷新')
    return row


def medication_revision(row, user_id, fields):
    return MedicationRevision(owner_id=user_id, medication_id=row.id, changed_by_id=user_id,
        from_version=row.version, snapshot=medication_json(row), changed_fields=fields)


@router.patch('/{medication_id}')
async def update_medication(medication_id: UUID, data: MedicationUpdate,
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await locked_medication(db, user.id, medication_id, data.expected_version)
    if row.deleted_at:
        raise HTTPException(409, '请先从回收站恢复药品')
    fields = data.model_fields_set - {'expected_version'}
    if fields:
        db.add(medication_revision(row, user.id, sorted(fields)))
        for key, value in data.model_dump(exclude={'expected_version'}, exclude_unset=True).items():
            setattr(row, key, value)
        row.version += 1
        await db.commit()
    return medication_json(row)


@router.post('/{medication_id}/trash')
async def trash_medication(medication_id: UUID, data: MedicationLifecycleUpdate,
                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await locked_medication(db, user.id, medication_id, data.expected_version)
    if row.deleted_at:
        raise HTTPException(409, '药品已在回收站')
    db.add(medication_revision(row, user.id, ['deleted_at']))
    row.deleted_at = datetime.now(timezone.utc)
    row.version += 1
    await db.commit()
    return medication_json(row)


@router.post('/{medication_id}/restore')
async def restore_medication(medication_id: UUID, data: MedicationLifecycleUpdate,
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await locked_medication(db, user.id, medication_id, data.expected_version)
    if not row.deleted_at:
        raise HTTPException(409, '药品不在回收站')
    db.add(medication_revision(row, user.id, ['deleted_at']))
    row.deleted_at = None
    row.version += 1
    await db.commit()
    return medication_json(row)


@router.get('/{medication_id}/revisions')
async def list_medication_revisions(medication_id: UUID, user: User = Depends(get_current_user),
                                    db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(Medication.id).where(Medication.id == medication_id,
        Medication.owner_id == user.id))
    if not row:
        raise HTTPException(404, '药品不存在')
    revisions = (await db.scalars(select(MedicationRevision).where(
        MedicationRevision.medication_id == medication_id, MedicationRevision.owner_id == user.id)
        .order_by(MedicationRevision.created_at.desc()))).all()
    return {'items': [{'from_version': rev.from_version, 'snapshot': rev.snapshot,
                       'changed_fields': rev.changed_fields, 'created_at': rev.created_at.isoformat()}
                      for rev in revisions]}


@router.get("/{medication_id}")
async def get_medication(medication_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    item = await db.scalar(select(Medication).where(Medication.id == medication_id, Medication.owner_id == user.id))
    if not item:
        raise HTTPException(404, "药品不存在")
    events = (await db.scalars(select(MedicationEvent).where(MedicationEvent.medication_id == item.id, MedicationEvent.owner_id == user.id).order_by(MedicationEvent.created_at))).all()
    sources = (await db.scalars(select(MedicationSource).where(MedicationSource.medication_id == item.id, MedicationSource.owner_id == user.id))).all()
    result = medication_json(item)
    packages = (await db.scalars(select(MedicationPackage).where(MedicationPackage.medication_id == item.id, MedicationPackage.owner_id == user.id))).all()
    result['packages'] = [package_json(p) for p in packages]
    result["events"] = [{
        "id": str(event.id), "event_type": event.event_type,
        "event_date": event.event_date.isoformat(), "from_status": event.from_status,
        "to_status": event.to_status, "dose_each_time": event.dose_each_time,
        "frequency": event.frequency, "timing": event.timing, "note": event.note,
    } for event in events]
    result["sources"] = [{
        "id": str(source.id), "document_id": str(source.document_id),
        "instructions": source.instructions, "purpose_text": source.purpose_text,
    } for source in sources]
    return result


@router.post("/{medication_id}/events", status_code=201)
async def create_event(data: MedicationEventInput, medication_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    item = await append_event(db, user, medication_id, data)
    return medication_json(item)
