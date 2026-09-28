import asyncio
from datetime import date, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from app.models import Document, LabResult
from app.services.metric_discovery import discover_metrics
from tests.test_uploads import setup_admin


def seed_labs(session_factory, owner_id, names):
    async def seed():
        async with session_factory() as db:
            labs = []
            for index, name in enumerate(names):
                day = date(2026, 1, 1) + timedelta(days=index)
                document = Document(owner_id=owner_id, document_type='检验报告',
                                    title=name, primary_date=day, patient_scope='self')
                db.add(document)
                await db.flush()
                lab = LabResult(owner_id=owner_id, document_id=document.id,
                                name=name, analyte_key=f'custom_{index}_{name}',
                                result=str(index + 1), unit='mg/L', observed_date=day,
                                result_type='numeric', review_status='confirmed')
                db.add(lab)
                labs.append(lab)
            await db.flush()
            await discover_metrics(db, owner_id, labs)
            await db.commit()
    asyncio.run(seed())


def test_dashboard_starts_with_ten_results_and_manual_change_freezes_membership(client, session_factory):
    owner = setup_admin(client)
    seed_labs(session_factory, UUID(owner['id']), [f'测试项目 {index}' for index in range(11)])

    overview = client.get('/api/overview').json()
    assert len(overview['metrics']) == 10
    assert len([item for item in overview['metric_catalog'] if item['record_count']]) == 11
    assert overview['metrics'][0]['name'] == '测试项目 10'
    selected_ids = {item['id'] for item in overview['metrics']}
    hidden = overview['metrics'][0]
    response = client.patch(f"/api/metrics/{hidden['id']}", json={
        'expected_version': hidden['version'], 'dashboard_visible': False,
    })
    assert response.status_code == 200
    assert response.json()['dashboard_visible'] is False

    after = client.get('/api/overview').json()
    assert len(after['metrics']) == 9
    assert hidden['id'] not in {item['id'] for item in after['metrics']}
    available = next(item for item in after['metric_catalog'] if item['id'] not in selected_ids)
    add = client.patch(f"/api/metrics/{available['id']}", json={
        'expected_version': available['version'], 'dashboard_visible': True,
    })
    assert add.status_code == 200
    final = client.get('/api/overview').json()
    assert len(final['metrics']) == 10
    assert available['id'] in {item['id'] for item in final['metrics']}


def test_dashboard_automatically_fills_available_places_before_customization(client, session_factory):
    owner = setup_admin(client)
    owner_id = UUID(owner['id'])
    seed_labs(session_factory, owner_id, ['第一项', '第二项'])
    assert len(client.get('/api/overview').json()['metrics']) == 2
    seed_labs(session_factory, owner_id, ['第三项'])
    assert len(client.get('/api/overview').json()['metrics']) == 3


def test_qualitative_reports_keep_separate_text_history_without_curve(client, session_factory):
    owner = setup_admin(client)
    owner_id = UUID(owner['id'])

    async def seed():
        async with session_factory() as db:
            labs = []
            for title, result in [('报告甲', '阴性'), ('报告乙', '阳性')]:
                document = Document(owner_id=owner_id, document_type='检验报告',
                                    title=title, primary_date=date(2026, 8, 1), patient_scope='self')
                db.add(document)
                await db.flush()
                lab = LabResult(owner_id=owner_id, document_id=document.id,
                                name='结核分枝杆菌', analyte_key='mtb_screen', result=result,
                                observed_date=date(2026, 8, 1), result_type='qualitative',
                                review_status='confirmed')
                db.add(lab)
                labs.append(lab)
            await db.flush()
            await discover_metrics(db, owner_id, labs)
            await db.commit()
    asyncio.run(seed())

    overview = client.get('/api/overview').json()
    metric = next(item for item in overview['metrics'] if item['name'] == '结核分枝杆菌')
    assert metric['record_type'] == 'qualitative'
    assert metric['record_count'] == 2
    assert metric['latest_result'] in {'阴性', '阳性'}
    assert metric['trend_series'] == []
    results = client.get(f"/api/metrics/{metric['id']}/results").json()['items']
    assert {item['raw_value'] for item in results} == {'阴性', '阳性'}
    assert len({item['source_id'] for item in results}) == 2
    assert all(item['value1'] is None for item in results)


def test_dashboard_selection_is_private_to_each_account(client, app, session_factory):
    owner = setup_admin(client)
    seed_labs(session_factory, UUID(owner['id']), ['私有指标'])
    metric = client.get('/api/overview').json()['metrics'][0]
    invitation = client.post('/api/admin/invitations', json={
        'email': 'other-dashboard@example.test',
    }).json()
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation', json={
            'token': invitation['token'], 'password': 'Correct-Horse-43',
        })
        response = other.patch(f"/api/metrics/{metric['id']}", json={
            'expected_version': metric['version'], 'dashboard_visible': False,
        })
        assert response.status_code == 404
        assert other.get('/api/overview').json()['metrics'] == []
    assert client.get('/api/overview').json()['metrics'][0]['id'] == metric['id']
