import asyncio
from decimal import Decimal
from uuid import UUID

from app.models import Document, LabResult, MetricEntry, User
from tests.test_uploads import setup_admin


def metric(client, key):
    return next(x for x in client.get('/api/metrics').json()['items'] if x['key'] == key)


def test_metric_results_merge_manual_and_matching_report_values(client, session_factory):
    owner = setup_admin(client)
    target = metric(client, 'fasting_glucose')

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            doc = Document(owner_id=user.id, document_type='检验报告', title='合成血糖报告',
                           primary_date_raw='2026-02-30', patient_scope='self')
            db.add(doc)
            await db.flush()
            db.add_all([
                LabResult(owner_id=user.id, document_id=doc.id, name='葡萄糖', analyte_key='glucose',
                          result='5.8', unit='mmol/L', condition='空腹', result_type='numeric',
                          review_status='confirmed'),
                LabResult(owner_id=user.id, document_id=doc.id, name='葡萄糖', analyte_key='glucose',
                          result='1+', unit='mmol/L', condition='空腹', result_type='qualitative',
                          review_status='confirmed'),
                LabResult(owner_id=user.id, document_id=doc.id, name='葡萄糖', analyte_key='glucose',
                          result='6.2', unit='mmol/L', condition='餐后', result_type='numeric',
                          review_status='confirmed'),
            ])
            await db.commit()

    asyncio.run(seed())
    client.post('/api/metric-entries', json={
        'metric_id': target['id'], 'record_date': '2026-09-11', 'raw_value': '0',
        'value1': '0', 'unit': 'mmol/L', 'condition': '空腹', 'review_status': 'confirmed',
        'idempotency_key': 'query-zero',
    })
    response = client.get(f"/api/metrics/{target['id']}/results")
    assert response.status_code == 200
    body = response.json()
    assert [Decimal(x['value1']) for x in body['items']] == [Decimal('0'), Decimal('5.8')]
    assert {x['source_type'] for x in body['items']} == {'manual', 'lab_report'}
    assert body['excluded']['non_numeric'] == 1
    assert body['excluded']['condition_mismatch'] == 1
    assert body['items'][1]['record_date'] is None


def test_metric_results_exclude_documents_not_confirmed_as_self(client, session_factory):
    owner = setup_admin(client)
    target = metric(client, 'fasting_glucose')

    async def seed():
        async with session_factory() as db:
            for scope in ['other', 'unconfirmed']:
                doc = Document(owner_id=UUID(owner['id']), document_type='检验报告', title=f'{scope} 的报告',
                               patient_scope=scope)
                db.add(doc); await db.flush()
                db.add(LabResult(owner_id=doc.owner_id, document_id=doc.id, name='葡萄糖', analyte_key='glucose',
                                 result='5.8', unit='mmol/L', condition='空腹', result_type='numeric',
                                 review_status='confirmed'))
            await db.commit()

    asyncio.run(seed())
    body = client.get(f"/api/metrics/{target['id']}/results").json()
    assert body['items'] == []
    assert body['excluded']['patient_scope'] == 2


def test_metric_results_are_owner_scoped(client, app):
    setup_admin(client)
    target = metric(client, 'weight')
    invitation = client.post('/api/admin/invitations', json={'email': 'query-other@example.test'}).json()
    from fastapi.testclient import TestClient
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation', json={'token': invitation['token'], 'password': 'Correct-Horse-43'})
        assert other.get(f"/api/metrics/{target['id']}/results").status_code == 404
