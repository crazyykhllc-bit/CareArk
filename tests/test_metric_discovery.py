import asyncio
from uuid import UUID

from sqlalchemy import select

from app.models import Document, LabResult, MetricDefinition
from app.services.metric_discovery import discover_metrics
from tests.test_uploads import setup_admin


def test_unknown_lab_creates_one_owner_scoped_metric_and_reuses_alias(session_factory, client):
    owner = setup_admin(client)

    async def run():
        async with session_factory() as db:
            doc = Document(owner_id=UUID(owner['id']), document_type='检验报告', title='肾功能',
                           patient_scope='self')
            db.add(doc)
            await db.flush()
            first = LabResult(owner_id=doc.owner_id, document_id=doc.id, name='胱抑素 C',
                              analyte_key='cystatin_c', result='0.91', unit='mg/L',
                              result_type='numeric', review_status='confirmed')
            second = LabResult(owner_id=doc.owner_id, document_id=doc.id, name='血清胱抑素C',
                               analyte_key='cystatin_c', result='0.95', unit='mg/L',
                               result_type='numeric', review_status='confirmed')
            db.add_all([first, second])
            await db.flush()
            await discover_metrics(db, doc.owner_id, [first, second])
            await db.commit()
            rows = (await db.scalars(select(MetricDefinition).where(
                MetricDefinition.owner_id == doc.owner_id,
                MetricDefinition.key == 'lab:cystatin_c',
            ))).all()
            return rows

    rows = asyncio.run(run())
    assert len(rows) == 1
    assert rows[0].group_name == '其他检验指标'
    assert rows[0].record_type == 'numeric'
    assert rows[0].unit == 'mg/L'
    assert set(rows[0].aliases) == {'胱抑素 C', '血清胱抑素C'}


def test_known_fasting_glucose_uses_preset_instead_of_unknown(session_factory, client):
    owner = setup_admin(client)

    async def run():
        async with session_factory() as db:
            doc = Document(owner_id=UUID(owner['id']), document_type='检验报告', title='血糖',
                           patient_scope='self')
            db.add(doc)
            await db.flush()
            lab = LabResult(owner_id=doc.owner_id, document_id=doc.id, name='葡萄糖',
                            analyte_key='glucose', result='5.2', unit='mmol/L', condition='空腹',
                            result_type='numeric', review_status='confirmed')
            db.add(lab)
            await db.flush()
            await discover_metrics(db, doc.owner_id, [lab])
            await db.commit()
            keys = set((await db.scalars(select(MetricDefinition.key).where(
                MetricDefinition.owner_id == doc.owner_id))).all())
            return keys

    keys = asyncio.run(run())
    assert 'fasting_glucose' in keys
    assert 'lab:glucose' not in keys


def test_same_analyte_creates_independent_metric_for_each_owner(session_factory, app):
    from fastapi.testclient import TestClient

    with TestClient(app) as admin:
        first = setup_admin(admin)
        invitation = admin.post('/api/admin/invitations', json={'email': 'metric-owner@example.test'}).json()
    with TestClient(app) as other:
        second = other.post('/api/auth/register/invitation', json={
            'token': invitation['token'], 'password': 'Correct-Horse-43',
        }).json()

    async def run():
        async with session_factory() as db:
            for owner in [UUID(first['id']), UUID(second['id'])]:
                doc = Document(owner_id=owner, document_type='检验报告', title='自定义项目',
                               patient_scope='self')
                db.add(doc)
                await db.flush()
                lab = LabResult(owner_id=owner, document_id=doc.id, name='项目 X', analyte_key='item_x',
                                result='1', unit='U/L', result_type='numeric', review_status='confirmed')
                db.add(lab)
                await db.flush()
                await discover_metrics(db, owner, [lab])
            await db.commit()
            return (await db.scalars(select(MetricDefinition).where(
                MetricDefinition.key == 'lab:item_x'))).all()

    rows = asyncio.run(run())
    assert {str(row.owner_id) for row in rows} == {first['id'], second['id']}
