import asyncio
import uuid
from datetime import date
from types import SimpleNamespace

from app.models import Medication, User
from app.services.batch_confirmation import resolve_medication
from tests.test_uploads import setup_admin


async def create_medication(session_factory, owner_id, *, expired=False):
    async with session_factory() as db:
        medication = Medication(
            owner_id=uuid.UUID(owner_id),
            drug_key="test-drug",
            name="测试药品",
            status="备用药",
            expiry_date=date(2020, 1, 1) if expired else date(2030, 1, 1),
        )
        db.add(medication)
        await db.commit()
        return medication.id


def test_start_pause_stop_append_independent_events(client, session_factory):
    user = setup_admin(client)
    medication_id = asyncio.run(create_medication(session_factory, user["id"]))

    started = client.post(f"/api/medications/{medication_id}/events", json={
        "event_type": "start",
        "event_date": "2026-09-06",
        "dose_each_time": "1喷",
        "frequency": "每日 1 次",
        "timing": "早晨",
        "expected_version": 1,
    })
    assert started.status_code == 201
    assert started.json()["status"] == "正在服用"
    assert started.json()["version"] == 2

    paused = client.post(f"/api/medications/{medication_id}/events", json={
        "event_type": "pause", "event_date": "2026-09-07", "expected_version": 2,
    })
    assert paused.json()["status"] == "备用药"

    stopped = client.post(f"/api/medications/{medication_id}/events", json={
        "event_type": "stop", "event_date": "2026-09-08", "expected_version": 3,
    })
    assert stopped.json()["status"] == "已停用"
    assert len(client.get(f"/api/medications/{medication_id}").json()["events"]) == 3


def test_stale_version_is_rejected(client, session_factory):
    user = setup_admin(client)
    medication_id = asyncio.run(create_medication(session_factory, user["id"]))
    payload = {
        "event_type": "start", "event_date": "2026-09-06", "dose_each_time": "1片",
        "frequency": "每日 1 次", "expected_version": 1,
    }
    assert client.post(f"/api/medications/{medication_id}/events", json=payload).status_code == 201
    assert client.post(f"/api/medications/{medication_id}/events", json=payload).status_code == 409


def test_expired_medication_cannot_be_started(client, session_factory):
    user = setup_admin(client)
    medication_id = asyncio.run(create_medication(session_factory, user["id"], expired=True))
    response = client.post(f"/api/medications/{medication_id}/events", json={
        "event_type": "start", "event_date": "2026-09-06", "dose_each_time": "1片",
        "frequency": "每日 1 次", "expected_version": 1,
    })

    assert response.status_code == 409
    assert response.json()["detail"] == "该药品已过期，不能开始用药"


def test_medication_edit_trash_restore_keeps_history_and_owner_scope(client, session_factory, app):
    user = setup_admin(client)
    medication_id = asyncio.run(create_medication(session_factory, user['id']))
    edited = client.patch(f'/api/medications/{medication_id}', json={
        'expected_version': 1, 'name': '修正药名', 'dose_each_time': '1片',
    })
    assert edited.status_code == 200
    assert edited.json()['version'] == 2
    assert edited.json()['name'] == '修正药名'
    assert client.patch(f'/api/medications/{medication_id}', json={
        'expected_version': 1, 'name': '旧版本',
    }).status_code == 409
    removed = client.post(f'/api/medications/{medication_id}/trash', json={'expected_version': 2})
    assert removed.status_code == 200
    assert client.get('/api/medications').json()['items'] == []
    assert client.get('/api/medications/trash').json()['items'][0]['name'] == '修正药名'
    assert client.post(f'/api/medications/{medication_id}/events', json={
        'event_type': 'start', 'event_date': '2026-09-24', 'expected_version': 3,
        'dose_each_time': '1片', 'frequency': '每日 1 次',
    }).status_code == 404
    restored = client.post(f'/api/medications/{medication_id}/restore', json={'expected_version': 3})
    assert restored.status_code == 200
    assert restored.json()['deleted_at'] is None
    assert client.get('/api/medications').json()['items'][0]['name'] == '修正药名'
    history = client.get(f'/api/medications/{medication_id}/revisions').json()['items']
    assert len(history) == 3
    assert history[-1]['snapshot']['name'] == '测试药品'

    invitation = client.post('/api/admin/invitations', json={'email': 'drug-other@example.test'}).json()
    from fastapi.testclient import TestClient
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation', json={
            'token': invitation['token'], 'password': 'Correct-Horse-43',
        })
        assert other.patch(f'/api/medications/{medication_id}', json={
            'expected_version': 4, 'name': '越权',
        }).status_code == 404


def test_new_confirmed_source_reactivates_trashed_medication(client, session_factory):
    user = setup_admin(client)
    medication_id = asyncio.run(create_medication(session_factory, user['id']))
    assert client.post(f'/api/medications/{medication_id}/trash',
                       json={'expected_version': 1}).status_code == 200

    async def attach_new_source():
        async with session_factory() as db:
            owner = await db.get(User, uuid.UUID(user['id']))
            item = SimpleNamespace(existing_medication_id=medication_id, name='测试药品',
                                   strength=None, dosage_form=None, manufacturer=None,
                                   approval_number=None)
            medication = await resolve_medication(db, owner, item)
            assert medication.id == medication_id
            await db.commit()

    asyncio.run(attach_new_source())
    assert client.get('/api/medications').json()['items'][0]['version'] == 3
    assert client.get('/api/medications/trash').json()['items'] == []
    history = client.get(f'/api/medications/{medication_id}/revisions').json()['items']
    assert history[0]['changed_fields'] == ['deleted_at', 'new_source']
