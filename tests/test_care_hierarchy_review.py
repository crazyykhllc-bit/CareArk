import asyncio
import json
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

from sqlalchemy import event

from app.models import Document, LabResult, MetricDefinition
from tests.test_care_history import seed_records
from tests.test_care_hierarchy import upgrade
from tests.test_uploads import setup_admin


def test_trashed_parent_projects_independent_and_allows_new_upgrade(client, session_factory):
    owner = setup_admin(client)
    event_id, _, _, _ = seed_records(session_factory, owner['id'])
    parent = upgrade(client, event_id)
    trashed = client.post(f"/api/care-topics/{parent['topic_id']}/trash",
        json={'expected_version': parent['topic_version']})
    assert trashed.status_code == 200
    event = client.get(f'/api/care-history/events/{event_id}').json()
    assert event['primary_topic_id'] is None
    card = client.get('/api/care-hierarchy?query=住院').json()['items'][0]
    assert card['item_type'] == 'event'
    assert card['primary_topic_id'] is None
    replacement = upgrade(client, event_id, event['version'], '新的合成过程')
    assert replacement['topic_id'] != parent['topic_id']
    restored = client.post(f"/api/care-topics/{parent['topic_id']}/restore",
        json={'expected_version': trashed.json()['version'] + 1})
    assert restored.status_code == 200
    assert client.get(f'/api/care-history/events/{event_id}').json()['primary_topic_id'] == replacement['topic_id']


def test_event_export_preserves_primary_and_related_membership(client, session_factory):
    owner = setup_admin(client)
    event_id, second_id, _, _ = seed_records(session_factory, owner['id'])
    parent = upgrade(client, event_id)
    reference = upgrade(client, second_id)
    linked = client.put(f'/api/care-history/events/{event_id}/parent', json={
        'expected_version': parent['version'], 'topic_id': reference['topic_id'], 'action': 'reference'})
    assert linked.status_code == 200
    response = client.get('/api/export')
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    event = next(x for x in manifest['encounters'] if x['id'] == str(event_id))
    assert event['primary_topic_id'] == parent['topic_id']
    assert {x['topic_id'] for x in manifest['care_topic_encounters']
        if x['encounter_id'] == str(event_id)} == {parent['topic_id'], reference['topic_id']}


def test_topic_metrics_follow_confirmed_self_and_valid_result_policy(client, session_factory):
    owner = setup_admin(client)
    event_id, _, _, _ = seed_records(session_factory, owner['id'])
    parent = upgrade(client, event_id)

    async def seed():
        async with session_factory() as db:
            metric = MetricDefinition(owner_id=UUID(owner['id']), key='lab:review_synthetic',
                name='合成核对指标', group_name='合成', record_type='numeric', aliases=['合成核对指标'])
            db.add(metric)
            for scope, status, result in [('self', 'confirmed', '1.2'), ('self', 'pending', '2'),
                ('self', 'excluded', '3'), ('other', 'confirmed', '4'),
                ('unconfirmed', 'confirmed', '5'), ('self', 'confirmed', '无法比较')]:
                doc = Document(owner_id=UUID(owner['id']), encounter_id=event_id,
                    document_type='检验报告', title='合成核对报告', patient_scope=scope)
                db.add(doc)
                await db.flush()
                db.add(LabResult(owner_id=UUID(owner['id']), document_id=doc.id,
                    name='合成核对指标', analyte_key='review_synthetic', result=result, review_status=status))
            await db.commit()
            return str(metric.id)

    metric_id = asyncio.run(seed())
    existing = client.get(f'/api/metrics/{metric_id}/results').json()
    assert len(existing['items']) == 1
    detail = client.get(f"/api/care-topics/{parent['topic_id']}/overview").json()
    summary = next(x for x in detail['metric_summaries'] if x['metric_id'] == metric_id)
    assert summary['result_count'] == len(existing['items'])
    assert summary['latest']['result'] == '1.2'


def test_topic_overview_does_not_query_labs_once_per_metric(client, session_factory):
    owner = setup_admin(client)
    event_id, _, _, _ = seed_records(session_factory, owner['id'])
    parent = upgrade(client, event_id)

    async def seed():
        async with session_factory() as db:
            db.add_all(MetricDefinition(owner_id=UUID(owner['id']), key=f'lab:unrelated_{index}',
                name=f'无关指标 {index}', group_name='合成', record_type='numeric')
                for index in range(24))
            await db.commit()

    asyncio.run(seed())
    engine = session_factory.kw['bind'].sync_engine
    selects = []

    def count_select(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith('select'):
            selects.append(statement)

    event.listen(engine, 'before_cursor_execute', count_select)
    try:
        response = client.get(f"/api/care-topics/{parent['topic_id']}/overview")
    finally:
        event.remove(engine, 'before_cursor_execute', count_select)
    assert response.status_code == 200
    assert len(selects) < 20
