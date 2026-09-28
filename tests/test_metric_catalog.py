from tests.test_uploads import setup_admin


def test_metric_catalog_is_initialized_without_fake_results(client):
    setup_admin(client)
    metrics = client.get('/api/metrics')
    assert metrics.status_code == 200
    items = metrics.json()['items']
    assert {'fasting_glucose', 'blood_pressure', 'blood_lipids', 'ogtt_glucose'} <= {x['key'] for x in items}
    assert client.get('/api/metric-entries').json()['items'] == []


def test_custom_metric_and_follow_state_use_versions(client):
    setup_admin(client)
    created = client.post('/api/metrics', json={
        'name': '合成自定义指标', 'group': '其他', 'record_type': 'numeric', 'unit': 'U/L',
        'aliases': ['合成别名'], 'followed': True,
    })
    assert created.status_code == 201
    metric = created.json()
    changed = client.patch(f"/api/metrics/{metric['id']}", json={
        'expected_version': metric['version'], 'followed': False,
    })
    assert changed.status_code == 200
    assert changed.json()['followed'] is False
    stale = client.patch(f"/api/metrics/{metric['id']}", json={
        'expected_version': metric['version'], 'followed': True,
    })
    assert stale.status_code == 409


def test_custom_metric_rejects_whitespace_only_names(client):
    setup_admin(client)
    response = client.post('/api/metrics', json={
        'name': '   ', 'group': '其他', 'record_type': 'numeric', 'unit': 'U/L',
    })
    assert response.status_code == 422
