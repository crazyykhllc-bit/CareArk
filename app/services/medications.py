from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Medication, MedicationEvent, MedicationPackage, MedicationRevision, User
from app.schemas import MedicationEventInput


def medication_json(item: Medication) -> dict:
    return {
        "id": str(item.id), "drug_key": item.drug_key, "name": item.name,
        "generic_name": item.generic_name, "brand_name": item.brand_name,
        "strength": item.strength, "dosage_form": item.dosage_form,
        "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
        "quantity": item.quantity, "status": item.status,
        "dose_each_time": item.dose_each_time, "frequency": item.frequency,
        "timing": item.timing, "route": item.route,
        "start_date": item.start_date.isoformat() if item.start_date else None,
        "planned_end_date": item.planned_end_date.isoformat() if item.planned_end_date else None,
        "version": item.version,
        "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
        "manufacturer": item.manufacturer, "approval_number": item.approval_number,
    }


def restore_from_new_source(db: AsyncSession, user: User, medication: Medication) -> None:
    """A newly confirmed source for the same product makes a trashed medicine active again."""
    if medication.deleted_at is None:
        return
    db.add(MedicationRevision(owner_id=user.id, medication_id=medication.id,
        changed_by_id=user.id, from_version=medication.version,
        snapshot=medication_json(medication), changed_fields=['deleted_at', 'new_source']))
    medication.deleted_at = None
    medication.version += 1


async def append_event(
    db: AsyncSession,
    user: User,
    medication_id: UUID,
    data: MedicationEventInput,
) -> Medication:
    medication = await db.scalar(
        select(Medication)
        .where(Medication.id == medication_id, Medication.owner_id == user.id,
               Medication.deleted_at.is_(None))
        .with_for_update()
    )
    if not medication:
        raise HTTPException(404, "药品不存在")
    if medication.version != data.expected_version:
        raise HTTPException(409, "药品资料已在其他位置更新，请刷新后重试")

    from_status = medication.status
    if data.event_type == "start":
        packages = (await db.scalars(select(MedicationPackage).where(MedicationPackage.medication_id == medication.id,
                                                                     MedicationPackage.owner_id == user.id))).all()
        expiry = medication.expiry_date
        if packages:
            selected = next((p for p in packages if p.id == data.package_id), None)
            if not selected:
                raise HTTPException(422, '请选择本次使用的药品包装')
            expiry = selected.expiry_date
        if expiry and expiry < data.event_date:
            raise HTTPException(409, "该药品已过期，不能开始用药")
        if from_status not in {"备用药", "已停用"}:
            raise HTTPException(409, "当前状态不能开始用药")
        if not data.dose_each_time or not data.frequency:
            raise HTTPException(422, "开始用药需要填写每次用量和频次")
        if data.planned_end_date and data.planned_end_date < data.event_date:
            raise HTTPException(422, "计划结束日期不能早于开始日期")
        to_status = "正在服用"
        medication.start_date = data.event_date
        medication.dose_each_time = data.dose_each_time
        medication.frequency = data.frequency
        medication.timing = data.timing
        medication.planned_end_date = data.planned_end_date
    elif data.event_type == "pause":
        if from_status != "正在服用":
            raise HTTPException(409, "只有正在服用的药品可以暂停")
        to_status = "备用药"
    else:
        if from_status not in {"正在服用", "备用药"}:
            raise HTTPException(409, "当前状态不能停止用药")
        to_status = "已停用"
        medication.planned_end_date = data.event_date

    medication.status = to_status
    medication.version += 1
    db.add(MedicationEvent(
        owner_id=user.id,
        medication_id=medication.id,
        event_type=data.event_type,
        event_date=data.event_date,
        from_status=from_status,
        to_status=to_status,
        dose_each_time=data.dose_each_time or medication.dose_each_time,
        frequency=data.frequency or medication.frequency,
        timing=data.timing or medication.timing,
        note=data.note,
    ))
    await db.commit()
    await db.refresh(medication)
    return medication
