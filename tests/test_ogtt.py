import asyncio
from datetime import date
from uuid import UUID

from app.models import Attachment, Document, LabResult, SourceUnit, UploadBatch, User
from tests.test_uploads import setup_admin


async def seed_same_day_ogtt(session_factory, owner_id):
    async with session_factory() as db:
        user = await db.get(User, UUID(owner_id))
        doc = Document(owner_id=user.id, document_type='检验报告', title='合成 OGTT',
                       primary_date=date(2026, 9, 11), hospital='合成医院', patient_scope='self')
        db.add(doc)
        await db.flush()
        first = LabResult(owner_id=user.id, document_id=doc.id, name='葡萄糖', analyte_key='glucose',
                          result='5.1', unit='mmol/L', timepoint_minutes=0,
                          observed_date=date(2026, 9, 11), result_type='numeric', review_status='confirmed')
        second = LabResult(owner_id=user.id, document_id=doc.id, name='葡萄糖', analyte_key='glucose',
                           result='1+', unit='mmol/L', timepoint_minutes=120,
                           observed_date=date(2026, 9, 11), result_type='qualitative', review_status='confirmed')
        db.add_all([first, second])
        await db.commit()
        return str(first.id), str(second.id)


def test_same_day_sources_stay_in_separate_ogtt_sessions_until_explicitly_linked(client, session_factory):
    owner = setup_admin(client)
    first, second = asyncio.run(seed_same_day_ogtt(session_factory, owner['id']))
    candidates = client.get('/api/test-sessions/candidates').json()['items']
    assert {x['id'] for x in candidates} == {first, second}
    ogtt_metric = next(x for x in client.get('/api/metrics').json()['items'] if x['key'] == 'ogtt_glucose')
    before_grouping = client.get(f"/api/metrics/{ogtt_metric['id']}/results").json()
    assert before_grouping['items'] == []
    assert before_grouping['excluded']['session_required'] == 2
    one = client.post('/api/test-sessions', json={
        'name': '上午试验', 'session_date': '2026-09-11', 'hospital': '合成医院',
        'lab_result_ids': [first],
    })
    two = client.post('/api/test-sessions', json={
        'name': '下午试验', 'session_date': '2026-09-11', 'hospital': '合成医院',
        'lab_result_ids': [second],
    })
    assert one.status_code == 201
    assert two.status_code == 201
    assert one.json()['id'] != two.json()['id']
    sessions = client.get('/api/test-sessions').json()['items']
    assert len(sessions) == 2
    assert sessions[0]['points'][0]['value'] is None
    assert sessions[0]['points'][0]['raw_value'] == '1+'
    assert sessions[1]['points'][0]['value'] == '5.1'
    results = client.get(f"/api/metrics/{ogtt_metric['id']}/results").json()
    assert len(results['items']) == 1
    assert results['items'][0]['series_key'] == 'glucose'
    assert client.get('/api/test-sessions/candidates').json()['items'] == []


def test_ogtt_session_cannot_claim_other_users_lab(client, app, session_factory):
    owner = setup_admin(client)
    first, _ = asyncio.run(seed_same_day_ogtt(session_factory, owner['id']))
    invitation = client.post('/api/admin/invitations', json={'email': 'ogtt-other@example.test'}).json()
    from fastapi.testclient import TestClient
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation', json={'token': invitation['token'], 'password': 'Correct-Horse-43'})
        response = other.post('/api/test-sessions', json={
            'name': '越权试验', 'session_date': '2026-09-11', 'lab_result_ids': [first],
        })
        assert response.status_code == 422


def test_ogtt_session_update_can_keep_the_same_sources(client, session_factory):
    owner = setup_admin(client)
    first, _ = asyncio.run(seed_same_day_ogtt(session_factory, owner['id']))

    async def seed_source():
        async with session_factory() as db:
            owner_id = UUID(owner['id'])
            batch = UploadBatch(owner_id=owner_id)
            attachment = Attachment(owner_id=owner_id, filename='ogtt.png', mime_type='image/png', size_bytes=1,
                                    sha256='a' * 64, object_key=f'{owner_id}/ogtt-source.png')
            db.add_all([batch, attachment]); await db.flush()
            source = SourceUnit(owner_id=owner_id, batch_id=batch.id, attachment_id=attachment.id,
                                ordinal=0, label='OGTT 第 1 页', kind='image')
            db.add(source); await db.commit(); return str(source.id)

    source_id = asyncio.run(seed_source())
    created = client.post('/api/test-sessions', json={
        'name': '可重复保存', 'session_date': '2026-09-11',
        'lab_result_ids': [first], 'source_unit_ids': [source_id],
    })
    assert created.status_code == 201
    updated = client.put(f"/api/test-sessions/{created.json()['id']}", json={
        'expected_version': 1, 'name': '可重复保存', 'session_date': '2026-09-11',
        'lab_result_ids': [first], 'source_unit_ids': [source_id],
    })
    assert updated.status_code == 200
    assert updated.json()['source_unit_ids'] == [source_id]
    assert updated.json()['points'][0]['document_id']
