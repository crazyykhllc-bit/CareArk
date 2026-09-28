import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.metric_schemas import MetricCreate, MetricUpdate, MetricEntryCreate, MetricEntryUpdate
from app.models import MetricDefinition, MetricEntry, MetricEntryRevision, User
from app.services.metric_catalog import ensure_catalog
from app.services.metric_queries import query_metric_results

router = APIRouter(prefix='/api')


def metric_json(row):
    return {'id': str(row.id), 'key': row.key, 'name': row.name, 'group': row.group_name,
            'record_type': row.record_type, 'unit': row.unit, 'aliases': row.aliases,
            'component_labels': row.component_labels, 'followed': row.followed,
            'dashboard_visible': row.dashboard_visible,
            'sort_order': row.sort_order, 'preset': row.preset, 'version': row.version}


def entry_json(row):
    return {'id': str(row.id), 'metric_id': str(row.metric_id), 'record_date': row.record_date.isoformat(),
            'raw_value': row.raw_value, 'value1': str(row.value1) if row.value1 is not None else None,
            'value2': str(row.value2) if row.value2 is not None else None, 'text_value': row.text_value,
            'unit': row.unit, 'condition': row.condition, 'review_status': row.review_status,
            'note': row.note, 'version': row.version, 'voided': row.voided_at is not None}


@router.get('/metrics')
async def list_metrics(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_catalog(db, user.id)
    rows = (await db.scalars(select(MetricDefinition).where(MetricDefinition.owner_id == user.id)
                            .order_by(MetricDefinition.sort_order, MetricDefinition.created_at))).all()
    return {'items': [metric_json(x) for x in rows]}


@router.post('/metrics', status_code=201)
async def create_metric(data: MetricCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_catalog(db, user.id)
    row = MetricDefinition(owner_id=user.id, key='custom_' + uuid.uuid4().hex, name=data.name.strip(),
        group_name=data.group.strip(), record_type=data.record_type, unit=data.unit.strip() if data.unit else None,
        aliases=[x.strip() for x in data.aliases if x.strip()], followed=data.followed,
        component_labels=data.component_labels, sort_order=1000, preset=False)
    db.add(row); await db.commit()
    return metric_json(row)


@router.patch('/metrics/{metric_id}')
async def update_metric(metric_id: uuid.UUID, data: MetricUpdate, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(MetricDefinition).where(MetricDefinition.id == metric_id,
        MetricDefinition.owner_id == user.id).with_for_update())
    if not row: raise HTTPException(404, '指标不存在')
    if row.version != data.expected_version: raise HTTPException(409, '指标已更新，请刷新')
    if data.followed is not None: row.followed = data.followed
    if data.dashboard_visible is not None:
        row.dashboard_visible = data.dashboard_visible
        user.dashboard_customized = True
    if data.sort_order is not None: row.sort_order = data.sort_order
    row.version += 1; await db.commit()
    return metric_json(row)


@router.get('/metrics/{metric_id}/results')
async def metric_results(metric_id: uuid.UUID, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    metric = await db.scalar(select(MetricDefinition).where(MetricDefinition.id == metric_id,
                                                             MetricDefinition.owner_id == user.id))
    if not metric:
        raise HTTPException(404, '指标不存在')
    result = await query_metric_results(db, user.id, metric)
    return {'metric': metric_json(metric), **result}


def validate_entry_type(metric, data):
    if not data.raw_value:
        raise HTTPException(422, '必须保留原始结果')
    text_value = data.text_value.strip() if data.text_value else None
    if metric.record_type == 'pair':
        if data.value1 is None or data.value2 is None:
            raise HTTPException(422, '双数值指标必须填写两个数值')
        if text_value:
            raise HTTPException(422, '双数值指标不能同时保存定性结果')
    if metric.record_type == 'numeric':
        if data.value1 is None:
            raise HTTPException(422, '数值指标必须填写结果')
        if data.value2 is not None or text_value:
            raise HTTPException(422, '单数值指标只能保存一个数值')
    if metric.record_type == 'qualitative':
        if not text_value:
            raise HTTPException(422, '定性指标必须填写文字结果')
        if data.value1 is not None or data.value2 is not None:
            raise HTTPException(422, '定性指标不能同时保存数值')
    if metric.record_type == 'group':
        raise HTTPException(422, '指标组请从报告或专用录入流程添加')


@router.get('/metric-entries')
async def list_entries(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
                       limit: int = Query(100, ge=1, le=200), cursor: int = Query(0, ge=0),
                       metric_id: uuid.UUID | None = None, voided: bool | None = None):
    query = select(MetricEntry).where(MetricEntry.owner_id == user.id)
    if metric_id is not None:
        query = query.where(MetricEntry.metric_id == metric_id)
    if voided is not None:
        query = query.where(MetricEntry.voided_at.is_not(None) if voided else MetricEntry.voided_at.is_(None))
    rows = list((await db.scalars(query
        .order_by(MetricEntry.record_date.desc(), MetricEntry.created_at.desc()).offset(cursor).limit(limit + 1))).all())
    more = len(rows) > limit
    return {'items': [entry_json(x) for x in rows[:limit]], 'next_cursor': cursor + limit if more else None}


@router.post('/metric-entries', status_code=201)
async def create_entry(data: MetricEntryCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(MetricEntry).where(MetricEntry.owner_id == user.id,
                                                          MetricEntry.idempotency_key == data.idempotency_key))
    if existing: return entry_json(existing)
    metric = await db.scalar(select(MetricDefinition).where(MetricDefinition.id == data.metric_id,
                                                             MetricDefinition.owner_id == user.id))
    if not metric: raise HTTPException(404, '指标不存在')
    validate_entry_type(metric, data)
    row = MetricEntry(owner_id=user.id, **data.model_dump())
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(MetricEntry).where(MetricEntry.owner_id == user.id,
                                                              MetricEntry.idempotency_key == data.idempotency_key))
        if existing:
            return entry_json(existing)
        raise
    return entry_json(row)


@router.patch('/metric-entries/{entry_id}')
async def update_entry(entry_id: uuid.UUID, data: MetricEntryUpdate, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(MetricEntry).where(MetricEntry.id == entry_id,
        MetricEntry.owner_id == user.id).with_for_update())
    if not row: raise HTTPException(404, '日常记录不存在')
    if row.version != data.expected_version: raise HTTPException(409, '记录已更新，请刷新')
    values = data.model_dump(exclude={'expected_version', 'voided'}, exclude_unset=True)
    if 'record_date' in values and values['record_date'] is None:
        raise HTTPException(422, '日期不能为空')
    metric = await db.scalar(select(MetricDefinition).where(MetricDefinition.id == row.metric_id,
                                                             MetricDefinition.owner_id == user.id))
    candidate = SimpleNamespace(**{name: values.get(name, getattr(row, name))
                                   for name in ['raw_value', 'value1', 'value2', 'text_value']})
    validate_entry_type(metric, candidate)
    if 'raw_value' in values and values['raw_value'] is None:
        raise HTTPException(422, '原始结果不能为空')
    if 'review_status' in values and values['review_status'] is None:
        raise HTTPException(422, '核对状态不能为空')
    changed_fields = list(values)
    if data.voided is not None:
        changed_fields.append('voided')
    if changed_fields:
        db.add(MetricEntryRevision(owner_id=user.id, metric_entry_id=row.id, changed_by_id=user.id,
            from_version=row.version, snapshot=entry_json(row), changed_fields=changed_fields))
    for name, value in values.items():
        setattr(row, name, value)
    if data.voided is True: row.voided_at = datetime.now(timezone.utc)
    elif data.voided is False: row.voided_at = None
    row.version += 1; await db.commit()
    return entry_json(row)


@router.get('/metric-entries/{entry_id}/revisions')
async def list_entry_revisions(entry_id: uuid.UUID, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(MetricEntry).where(MetricEntry.id == entry_id, MetricEntry.owner_id == user.id))
    if not row: raise HTTPException(404, '日常记录不存在')
    revisions = (await db.scalars(select(MetricEntryRevision).where(
        MetricEntryRevision.metric_entry_id == entry_id, MetricEntryRevision.owner_id == user.id
    ).order_by(MetricEntryRevision.created_at.desc()))).all()
    return {'items': [{'from_version': item.from_version, 'snapshot': item.snapshot,
                       'changed_fields': item.changed_fields, 'created_at': item.created_at.isoformat()}
                      for item in revisions]}
