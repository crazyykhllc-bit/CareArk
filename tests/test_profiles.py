import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Document, UploadBatch
from tests.test_uploads import setup_admin


def test_managed_member_switch_isolates_documents_and_uploads(app, session_factory):
    with TestClient(app) as client:
        account = setup_admin(client)

        async def seed_self():
            async with session_factory() as db:
                db.add(Document(owner_id=UUID(account['id']), document_type='门诊病历',
                                title='自己的资料', patient_scope='self'))
                await db.commit()

        asyncio.run(seed_self())
        assert client.get('/api/overview').json()['documents']['total'] == 1
        self_metric = client.post('/api/metrics', json={
            'name': '自己的专属指标', 'group': '自定义', 'record_type': 'numeric', 'unit': 'mg'}).json()
        assert client.post('/api/metric-entries', json={
            'metric_id': self_metric['id'], 'record_date': '2026-09-27',
            'raw_value': '5', 'value1': '5', 'unit': 'mg', 'idempotency_key': 'self-result'}).status_code == 201

        created = client.post('/api/profiles', json={'name': '姐姐'})
        assert created.status_code == 201
        assert created.json()['name'] == '姐姐'
        parent_id = created.json()['id']
        assert client.get('/api/profiles').json()['active_id'] == account['id']
        assert len(client.get('/api/admin/users').json()['items']) == 1
        assert client.post('/api/profiles/active', json={'profile_id': parent_id}).status_code == 200
        assert client.get('/api/profiles').json()['active_id'] == parent_id
        assert client.get('/api/auth/me').json()['id'] == account['id']
        assert client.get('/api/overview').json()['documents']['total'] == 0
        assert client.get('/api/documents').json()['items'] == []
        assert all(item['id'] != self_metric['id'] for item in client.get('/api/metrics').json()['items'])
        assert client.get(f"/api/metrics/{self_metric['id']}/results").status_code == 404
        assert client.get('/api/admin/users').status_code == 200

        async def seed_parent():
            async with session_factory() as db:
                db.add(Document(owner_id=UUID(parent_id), document_type='门诊病历',
                                title='姐姐的资料', patient_scope='self'))
                await db.commit()

        asyncio.run(seed_parent())
        assert client.get('/api/overview').json()['documents']['total'] == 1
        assert client.get('/api/documents').json()['items'][0]['title'] == '姐姐的资料'
        parent_metric = client.post('/api/metrics', json={
            'name': '姐姐的专属指标', 'group': '自定义', 'record_type': 'numeric'}).json()

        batch = client.post('/api/batches', json={})
        assert batch.status_code == 201

        async def check_batch():
            async with session_factory() as db:
                return (await db.scalar(select(UploadBatch).where(
                    UploadBatch.id == UUID(batch.json()['id'])))).owner_id

        assert asyncio.run(check_batch()) == UUID(parent_id)
        assert client.post('/api/profiles/active', json={'profile_id': account['id']}).status_code == 200
        assert client.get('/api/overview').json()['documents']['total'] == 1
        assert client.get('/api/documents').json()['items'][0]['title'] == '自己的资料'
        assert all(item['id'] != parent_metric['id'] for item in client.get('/api/metrics').json()['items'])
        assert client.get(f"/api/metrics/{parent_metric['id']}/results").status_code == 404
        assert client.get('/api/batches').json()['items'] == []


def test_account_cannot_switch_to_another_accounts_managed_member(app):
    with TestClient(app) as admin:
        setup_admin(admin)
        invite = admin.post('/api/admin/invitations', json={
            'email': 'sibling@example.test', 'expires_in_hours': 24}).json()
        with TestClient(app) as sibling:
            registered = sibling.post('/api/auth/register/invitation', json={
                'token': invite['token'], 'password': 'Correct-Horse-43'})
            assert registered.status_code == 201
            profile = sibling.post('/api/profiles', json={'name': '爸爸'}).json()
            assert admin.post('/api/profiles/active', json={
                'profile_id': profile['id']}).status_code == 404
            assert admin.get('/api/profiles').json()['active_id'] != profile['id']
            assert sibling.get('/api/profiles').json()['active_id'] == registered.json()['id']
