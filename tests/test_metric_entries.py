from decimal import Decimal

from tests.test_uploads import setup_admin


def metric(client, key):
    return next(x for x in client.get('/api/metrics').json()['items'] if x['key'] == key)


def test_zero_daily_metric_is_saved_and_idempotent(client):
    setup_admin(client)
    target = metric(client, 'fasting_glucose')
    payload = {'metric_id': target['id'], 'record_date': '2026-09-11', 'raw_value': '0',
               'value1': '0', 'unit': 'mmol/L', 'condition': '空腹',
               'review_status': 'confirmed', 'idempotency_key': 'daily-zero'}
    first = client.post('/api/metric-entries', json=payload)
    second = client.post('/api/metric-entries', json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()['id'] == second.json()['id']
    assert Decimal(first.json()['value1']) == Decimal('0')
    assert len(client.get('/api/metric-entries').json()['items']) == 1


def test_entry_type_must_match_metric(client):
    setup_admin(client)
    pressure = metric(client, 'blood_pressure')
    missing_second = client.post('/api/metric-entries', json={
        'metric_id': pressure['id'], 'record_date': '2026-09-11', 'raw_value': '120',
        'value1': '120', 'unit': 'mmHg', 'review_status': 'confirmed',
        'idempotency_key': 'bad-pressure',
    })
    assert missing_second.status_code == 422
    glucose = metric(client, 'fasting_glucose')
    extra_second = client.post('/api/metric-entries', json={
        'metric_id': glucose['id'], 'record_date': '2026-09-11', 'raw_value': '5.1',
        'value1': '5.1', 'value2': '99', 'unit': 'mmol/L', 'review_status': 'confirmed',
        'idempotency_key': 'bad-glucose-second-value',
    })
    assert extra_second.status_code == 422


def test_entry_update_revalidates_shape_and_supports_voiding(client):
    setup_admin(client)
    pressure = metric(client, 'blood_pressure')
    created = client.post('/api/metric-entries', json={
        'metric_id': pressure['id'], 'record_date': '2026-09-11', 'raw_value': '120/80',
        'value1': '120', 'value2': '80', 'unit': 'mmHg', 'review_status': 'confirmed',
        'idempotency_key': 'pressure-update',
    }).json()
    invalid = client.patch(f"/api/metric-entries/{created['id']}", json={
        'expected_version': created['version'], 'value2': None,
    })
    assert invalid.status_code == 422
    voided = client.patch(f"/api/metric-entries/{created['id']}", json={
        'expected_version': created['version'], 'voided': True,
    })
    assert voided.status_code == 200
    assert voided.json()['voided'] is True
    assert client.get('/api/metric-entries').json()['items'][0]['voided'] is True


def test_edit_trash_restore_manual_entry_updates_trend_and_history(client):
    setup_admin(client)
    glucose = metric(client, 'fasting_glucose')
    created = client.post('/api/metric-entries', json={
        'metric_id': glucose['id'], 'record_date': '2026-09-11', 'raw_value': '5.1',
        'value1': '5.1', 'unit': 'mmol/L', 'review_status': 'confirmed',
        'idempotency_key': 'correct-glucose',
    }).json()
    entry_id = created['id']
    edited = client.patch(f'/api/metric-entries/{entry_id}', json={
        'expected_version': created['version'], 'record_date': '2026-09-12',
        'raw_value': '5.4', 'value1': '5.4',
    })
    assert edited.status_code == 200
    assert edited.json()['record_date'] == '2026-09-12'
    results = client.get(f"/api/metrics/{glucose['id']}/results").json()['items']
    assert any(item['source_id'] == entry_id and item['raw_value'] == '5.4' for item in results)
    revision = client.get(f'/api/metric-entries/{entry_id}/revisions').json()['items'][0]
    assert revision['snapshot']['raw_value'] == '5.1'
    trashed = client.patch(f'/api/metric-entries/{entry_id}', json={
        'expected_version': edited.json()['version'], 'voided': True,
    }).json()
    assert client.get(f"/api/metrics/{glucose['id']}/results").json()['items'] == []
    assert len(client.get(f"/api/metric-entries?metric_id={glucose['id']}&voided=true").json()['items']) == 1
    restored = client.patch(f'/api/metric-entries/{entry_id}', json={
        'expected_version': trashed['version'], 'voided': False,
    })
    assert restored.status_code == 200
    assert len(client.get(f"/api/metrics/{glucose['id']}/results").json()['items']) == 1


def test_metric_entries_are_isolated_by_user(client, app):
    setup_admin(client)
    target = metric(client, 'fasting_glucose')
    client.post('/api/metric-entries', json={
        'metric_id': target['id'], 'record_date': '2026-09-11', 'raw_value': '5.1',
        'value1': '5.1', 'unit': 'mmol/L', 'review_status': 'confirmed',
        'idempotency_key': 'owner-only',
    })
    invitation = client.post('/api/admin/invitations', json={'email': 'metric-other@example.test'}).json()
    from fastapi.testclient import TestClient
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation', json={'token': invitation['token'], 'password': 'Correct-Horse-43'})
        assert other.get('/api/metric-entries').json()['items'] == []
        foreign = other.post('/api/metric-entries', json={
            'metric_id': target['id'], 'record_date': '2026-09-11', 'raw_value': '5.2',
            'value1': '5.2', 'unit': 'mmol/L', 'review_status': 'confirmed',
            'idempotency_key': 'foreign',
        })
        assert foreign.status_code == 404
