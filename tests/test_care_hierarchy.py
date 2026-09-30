import asyncio
from uuid import UUID

from sqlalchemy import select

from app.models import CareTopic, CareTopicExclusion, Document, Encounter, User, utcnow
from tests.test_care_history import seed_records
from tests.test_uploads import setup_admin


def upgrade(client, event, version=1, name='合成跨院经历'):
    response = client.post(f'/api/care-history/events/{event}/upgrade',
        json={'expected_version': version, 'name': name})
    assert response.status_code == 200, response.text
    return response.json()


def test_upgrade_is_idempotent_and_preserves_events_documents(client, session_factory):
    owner = setup_admin(client)
    first, second, source, _ = seed_records(session_factory, owner['id'])
    result = upgrade(client, first)
    repeated = upgrade(client, first)  # retry with original version is safe
    assert repeated['topic_id'] == result['topic_id']
    event = client.get(f'/api/care-history/events/{first}').json()
    assert event['primary_topic_id'] == result['topic_id']
    assert event['document_count'] == 2
    assert client.get(f'/api/documents/{source}').json()['encounter_id'] == str(first)
    listed = client.get('/api/care-hierarchy').json()
    assert listed['total'] == 2
    assert {(x['item_type'], x['id']) for x in listed['items']} == {
        ('event', str(second)), ('topic', result['topic_id'])}
    assert client.get(f"/api/care-topics/{result['topic_id']}/overview").json()['document_count'] == 2


def test_cross_hospital_parent_moves_and_detaches_without_copying(client, session_factory):
    owner = setup_admin(client)
    first, second, source, _ = seed_records(session_factory, owner['id'])
    topic = upgrade(client, first)['topic_id']
    moved = client.put(f'/api/care-history/events/{second}/parent',
        json={'expected_version':1, 'topic_id':topic, 'action':'move'})
    assert moved.status_code == 200, moved.text
    overview = client.get(f'/api/care-topics/{topic}/overview').json()
    assert overview['event_count'] == 2
    assert overview['hospital_count'] == 2
    assert overview['document_count'] == 3
    assert {x['id'] for x in overview['events']} == {str(first),str(second)}
    assert client.post(f'/api/care-topics/{topic}/downgrade',
        json={'expected_version':overview['version']}).status_code == 422
    detached = client.delete(f'/api/care-history/events/{second}/parent?expected_version={moved.json()["version"]}')
    assert detached.status_code == 200, detached.text
    assert client.get(f'/api/care-history/events/{second}').json()['primary_topic_id'] is None
    async def excluded():
        async with session_factory() as db:
            return await db.scalar(select(CareTopicExclusion.id).where(CareTopicExclusion.encounter_id == second))
    assert asyncio.run(excluded()) is not None
    detail = client.get(f'/api/care-topics/{topic}/overview').json()
    downgraded = client.post(f'/api/care-topics/{topic}/downgrade',json={'expected_version':detail['version']})
    assert downgraded.status_code == 200, downgraded.text
    assert downgraded.json()['event_id'] == str(first)
    assert client.get(f'/api/documents/{source}').status_code == 200
    assert client.get('/api/care-hierarchy').json()['total'] == 2


def test_filters_keep_all_hospital_choices_and_find_named_checkup_topic(client, session_factory):
    owner = setup_admin(client)
    first, second, _, _ = seed_records(session_factory, owner['id'])
    topic = upgrade(client, first, name='全面体检')['topic_id']
    moved = client.put(f'/api/care-history/events/{second}/parent',
        json={'expected_version': 1, 'topic_id': topic, 'action': 'move'})
    assert moved.status_code == 200, moved.text

    filtered = client.get('/api/care-hierarchy?hospital=乙医院').json()
    assert filtered['total'] == 1
    assert filtered['items'][0]['id'] == topic
    assert {item['name'] for item in filtered['hospitals']} == {'甲医院', '乙医院'}

    checkup = client.get('/api/care-hierarchy?hospital=乙医院&event_kind=checkup').json()
    assert checkup['total'] == 1
    assert checkup['items'][0]['id'] == topic
    assert {item['name'] for item in checkup['hospitals']} == {'甲医院', '乙医院'}


def test_attach_document_moves_whole_event_and_receipt_stays_source(client, session_factory):
    owner = setup_admin(client)
    first, second, source, loose = seed_records(session_factory, owner['id'])
    topic = upgrade(client, second)['topic_id']
    response = client.post(f'/api/care-topics/{topic}/attach-documents',
        json={'document_ids':[str(source),str(loose)]})
    assert response.status_code == 200, response.text
    overview = client.get(f'/api/care-topics/{topic}/overview').json()
    assert overview['event_count'] == 3
    assert overview['document_count'] == 4
    assert len({x['id'] for x in overview['documents']}) == 4
    assert client.get(f'/api/care-history/events/{first}').json()['document_count'] == 2


def test_create_big_with_documents_is_atomic(client, session_factory):
    owner = setup_admin(client)
    first, _, source, loose = seed_records(session_factory, owner['id'])
    response = client.post('/api/care-topics', json={'name':'合成新经历',
        'document_ids':[str(source),str(loose)]})
    assert response.status_code == 201, response.text
    topic = response.json()['id']
    assert client.get(f'/api/care-topics/{topic}/overview').json()['document_count'] == 3
    before = len(client.get('/api/care-topics').json()['items'])
    invalid = client.post('/api/care-topics', json={'name':'不能留下空容器',
        'document_ids':[str(source),'00000000-0000-0000-0000-000000000099']})
    assert invalid.status_code == 404
    assert len(client.get('/api/care-topics').json()['items']) == before


def test_attach_multiple_events_rolls_back_on_stale_version(client, session_factory):
    owner = setup_admin(client)
    first, second, _, _ = seed_records(session_factory, owner['id'])
    topic = client.post('/api/care-topics',json={'name':'合成批量经历'}).json()['id']
    response = client.post(f'/api/care-topics/{topic}/attach-events',json={
        'events':[{'id':str(first),'expected_version':1},{'id':str(second),'expected_version':99}]})
    assert response.status_code == 409
    assert client.get(f'/api/care-history/events/{first}').json()['primary_topic_id'] is None
    response = client.post(f'/api/care-topics/{topic}/attach-events',json={
        'events':[{'id':str(first),'expected_version':1},{'id':str(second),'expected_version':1}]})
    assert response.status_code == 200, response.text
    assert client.get(f'/api/care-topics/{topic}/overview').json()['event_count'] == 2


def test_group_recycle_restores_only_group_sources(client, session_factory):
    owner = setup_admin(client)
    first,second,source,loose = seed_records(session_factory,owner['id'])
    topic = upgrade(client,first)['topic_id']
    detail = client.get(f'/api/care-topics/{topic}/overview').json()
    response = client.post(f'/api/care-topics/{topic}/trash-group',json={'expected_version':detail['version']})
    assert response.status_code == 200,response.text
    assert response.json()['document_count'] == 2
    assert client.get(f'/api/documents/{source}').json()['deleted_at'] is not None
    assert client.get(f'/api/documents/{loose}').status_code == 200
    assert client.get(f'/api/care-history/events/{second}').status_code == 200
    response = client.post(f'/api/care-topics/{topic}/restore',json={'expected_version':response.json()['version']})
    assert response.status_code == 200,response.text
    assert client.get(f'/api/documents/{source}').status_code == 200
    assert client.get(f'/api/documents/{source}').json()['deleted_at'] is None
    assert client.get(f'/api/care-topics/{topic}/overview').json()['document_count'] == 2


def test_ambiguous_old_references_enter_review_and_resolve_without_copying(client,session_factory):
    from app.models import CareTopicEncounter
    owner=setup_admin(client)
    first,_,source,_=seed_records(session_factory,owner['id'])
    async def seed():
        async with session_factory() as db:
            topics=[CareTopic(owner_id=UUID(owner['id']),name=name) for name in ['旧主题一','旧主题二']]
            db.add_all(topics)
            await db.flush()
            db.add_all([CareTopicEncounter(owner_id=UUID(owner['id']),topic_id=t.id,encounter_id=first) for t in topics])
            await db.commit()
            return topics[0].id
    target=asyncio.run(seed())
    review=client.get('/api/care-hierarchy/ownership-review').json()
    assert review['total']==1
    assert review['items'][0]['id']==str(first)
    version=review['items'][0]['version']
    assert client.put(f'/api/care-history/events/{first}/parent',json={
        'expected_version':version,'topic_id':str(target)}).status_code==200
    assert client.get('/api/care-hierarchy/ownership-review').json()['total']==0
    assert len(client.get(f'/api/care-history/events/{first}').json()['topic_ids'])==2
    assert client.get(f'/api/documents/{source}').json()['encounter_id']==str(first)


def test_split_archived_sources_preserves_originals_and_parent(client,session_factory):
    owner=setup_admin(client)
    first,second,source,loose=seed_records(session_factory,owner['id'])
    parent=upgrade(client,first)['topic_id']
    event=client.get(f'/api/care-history/events/{first}').json()
    response=client.post(f'/api/care-history/events/{first}/split-documents',json={
        'expected_version':event['version'],'document_ids':[str(source)],'title':'独立检查资料'})
    assert response.status_code==200,response.text
    created=response.json()['event_id']
    assert created!=str(first)
    assert client.get(f'/api/documents/{source}').json()['encounter_id']==created
    assert client.get(f'/api/care-history/events/{created}').json()['primary_topic_id']==parent
    assert client.get(f'/api/care-topics/{parent}/overview').json()['document_count']==2
    response=client.post(f'/api/care-history/events/{second}/split-documents',json={
        'expected_version':1,'document_ids':[str(loose)],'title':'不能移动别的资料'})
    assert response.status_code==422


def test_split_requires_archived_parent_to_be_reopened(client,session_factory):
    owner=setup_admin(client)
    first,_,source,_=seed_records(session_factory,owner['id'])
    parent=upgrade(client,first)['topic_id']
    topic=client.get(f'/api/care-topics/{parent}/overview').json()
    assert client.patch(f'/api/care-topics/{parent}',json={
        'expected_version':topic['version'],'status':'archived'}).status_code==200
    event=client.get(f'/api/care-history/events/{first}').json()
    result=client.post(f'/api/care-history/events/{first}/split-documents',json={
        'expected_version':event['version'],'document_ids':[str(source)],'title':'归档后拆分'})
    assert result.status_code==409
    assert client.get(f'/api/documents/{source}').json()['encounter_id']==str(first)


def test_search_is_server_paginated_past_one_hundred_and_includes_children(client, session_factory):
    owner = setup_admin(client)
    first, _, _, _ = seed_records(session_factory, owner['id'])
    topic = upgrade(client, first)['topic_id']
    async def seed():
        async with session_factory() as db:
            db.add_all([Encounter(owner_id=UUID(owner['id']),title=f'合成检索 {i}') for i in range(125)])
            await db.commit()
    asyncio.run(seed())
    response = client.get('/api/care-hierarchy/search?kind=event&query=合成&offset=100&limit=20')
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 127
    assert len(response.json()['items']) == 20
    child = client.get('/api/care-hierarchy/search?kind=event&query=住院').json()['items'][0]
    assert child['primary_topic_id'] == topic


def test_reference_does_not_replace_parent_and_rejects_archived_deleted_other_owner(client, session_factory):
    owner = setup_admin(client)
    first, second, _, _ = seed_records(session_factory, owner['id'])
    parent = upgrade(client, first)['topic_id']
    other = upgrade(client, second)['topic_id']
    event = client.get(f'/api/care-history/events/{first}').json()
    response = client.put(f'/api/care-history/events/{first}/parent',
        json={'expected_version':event['version'],'topic_id':other,'action':'reference'})
    assert response.status_code == 200, response.text
    detail = client.get(f'/api/care-history/events/{first}').json()
    assert detail['primary_topic_id'] == parent
    assert other in detail['topic_ids']
    async def invalid_targets():
        async with session_factory() as db:
            stranger = User(email='synthetic-other@example.test',password_hash='synthetic')
            db.add(stranger); await db.flush()
            topics = [CareTopic(owner_id=UUID(owner['id']),name='合成归档',status='archived'),
                CareTopic(owner_id=UUID(owner['id']),name='合成删除',deleted_at=utcnow()),
                CareTopic(owner_id=stranger.id,name='合成他人')]
            db.add_all(topics); await db.commit()
            return [str(x.id) for x in topics]
    archived, deleted, foreign = asyncio.run(invalid_targets())
    for target, status in [(archived,409),(deleted,404),(foreign,404)]:
        invalid = client.put(f'/api/care-history/events/{first}/parent',json={
            'expected_version':detail['version'],'topic_id':target,'action':'move'})
        assert invalid.status_code == status
    assert client.get(f'/api/care-topics/{foreign}/overview').status_code == 404


def test_older_months_never_repeat_recent_cards_and_trashed_parent_releases_children(client, session_factory):
    from datetime import date
    owner = setup_admin(client)
    first, _, _, _ = seed_records(session_factory,owner['id'])
    parent = upgrade(client,first)['topic_id']
    async def seed():
        async with session_factory() as db:
            db.add_all([Encounter(owner_id=UUID(owner['id']),title=f'合成历史{i}',date=date(2026,4,1)) for i in range(12)])
            db.add(Encounter(owner_id=UUID(owner['id']),title='合成无日期'))
            await db.commit()
    asyncio.run(seed())
    recent = client.get('/api/care-hierarchy').json()
    older = client.get('/api/care-hierarchy?older=true&limit=100').json()
    assert len(recent['items']) == 10
    assert not ({x['id'] for x in recent['items']} & {x['id'] for x in older['items']})
    assert recent['older_months'][0] == {'month':'2026-04','count':2}
    assert recent['undated_count'] == 1
    assert client.get('/api/care-hierarchy?month=2026-04').json()['total'] == 2
    assert client.get('/api/care-hierarchy?month=undated').json()['total'] == 1
    topic = client.get(f'/api/care-topics/{parent}/overview').json()
    client.post(f'/api/care-topics/{parent}/trash',json={'expected_version':topic['version']})
    independent = client.get('/api/care-hierarchy?query=住院').json()
    assert independent['items'][0]['id'] == str(first)


def test_overview_excludes_reference_sources_and_duplicate_receipts_and_keeps_currencies(client,session_factory):
    from decimal import Decimal
    from app.models import LabResult, MetricDefinition, ReceiptDetail
    owner = setup_admin(client)
    first, second, _, _ = seed_records(session_factory,owner['id'])
    parent = upgrade(client,first)['topic_id']
    other = upgrade(client,second)['topic_id']
    version = client.get(f'/api/care-history/events/{second}').json()['version']
    client.put(f'/api/care-history/events/{second}/parent',json={
        'expected_version':version,'topic_id':parent,'action':'reference'})
    async def seed():
        async with session_factory() as db:
            for currency,amount,status in [('CNY','12.34','active'),('USD','5.00','active'),('CNY','12.34','duplicate')]:
                doc = Document(owner_id=UUID(owner['id']),encounter_id=first,document_type='收费单',title='合成票据')
                db.add(doc); await db.flush()
                db.add(ReceiptDetail(owner_id=UUID(owner['id']),document_id=doc.id,
                    total_amount=Decimal(amount),currency=currency,status=status))
            metric = MetricDefinition(owner_id=UUID(owner['id']),key='lab:synthetic',name='合成指标',
                group_name='合成',record_type='numeric',aliases=['合成指标'])
            db.add(metric)
            source = await db.scalar(select(Document).where(Document.encounter_id == first))
            db.add(LabResult(owner_id=UUID(owner['id']),document_id=source.id,name='合成指标',
                analyte_key='synthetic',result='1.2',review_status='confirmed'))
            await db.commit()
            return str(metric.id)
    metric_id = asyncio.run(seed())
    detail = client.get(f'/api/care-topics/{parent}/overview').json()
    assert detail['event_count'] == 1
    assert [x['id'] for x in detail['related_events']] == [str(second)]
    assert {x['currency']:x['total'] for x in detail['costs_by_currency']} == {'CNY':'12.34','USD':'5.00'}
    assert detail['metric_summaries'][0]['metric_id'] == metric_id
    assert detail['metric_summaries'][0]['result_count'] == 1


def test_upgrade_different_name_and_stale_parent_write_do_not_change_sources(client,session_factory):
    owner = setup_admin(client)
    first,second,_,_ = seed_records(session_factory,owner['id'])
    parent = upgrade(client,first)['topic_id']
    assert client.post(f'/api/care-history/events/{first}/upgrade',json={
        'expected_version':1,'name':'另一个合成过程'}).status_code == 409
    assert client.put(f'/api/care-history/events/{second}/parent',json={
        'expected_version':99,'topic_id':parent,'action':'move'}).status_code == 409
    assert client.get(f'/api/care-history/events/{second}').json()['primary_topic_id'] is None


def test_legacy_manual_topic_creation_and_removal_keep_primary_invariant(client,session_factory):
    owner = setup_admin(client)
    first,second,_,_ = seed_records(session_factory,owner['id'])
    topic = client.post('/api/care-topics',json={'name':'合成手动容器','event_ids':[str(first)]}).json()
    event = client.get(f'/api/care-history/events/{first}').json()
    assert event['primary_topic_id'] == topic['id']
    another = client.post('/api/care-topics',json={'name':'合成相关容器','event_ids':[str(first),str(second)]}).json()
    assert client.get(f'/api/care-history/events/{first}').json()['primary_topic_id'] == topic['id']
    assert client.get(f'/api/care-history/events/{second}').json()['primary_topic_id'] == another['id']
    assert client.delete(f'/api/care-topics/{topic["id"]}/events/{first}').status_code == 200
    detached = client.get(f'/api/care-history/events/{first}').json()
    assert detached['primary_topic_id'] is None
    assert detached['version'] > event['version']


def test_migration_assigns_only_one_valid_same_owner_topic(tmp_path):
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('hierarchy_migration',
        Path(__file__).parents[1]/'alembic/versions/0014_care_hierarchy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f'sqlite:///{tmp_path / "migration.db"}')
    metadata = sa.MetaData()
    sa.Table('care_topics',metadata,sa.Column('id',sa.String,primary_key=True),
        sa.Column('owner_id',sa.String),sa.Column('deleted_at',sa.DateTime))
    sa.Table('encounters',metadata,sa.Column('id',sa.String,primary_key=True),sa.Column('owner_id',sa.String))
    sa.Table('care_topic_encounters',metadata,sa.Column('topic_id',sa.String),
        sa.Column('encounter_id',sa.String),sa.Column('owner_id',sa.String))
    metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(metadata.tables['care_topics'].insert(),[
            {'id':'a','owner_id':'one','deleted_at':None},
            {'id':'b','owner_id':'one','deleted_at':None},
            {'id':'gone','owner_id':'one','deleted_at':utcnow()},
            {'id':'foreign','owner_id':'two','deleted_at':None}])
        db.execute(metadata.tables['encounters'].insert(),[
            {'id':'single','owner_id':'one'},{'id':'overlap','owner_id':'one'},
            {'id':'deleted','owner_id':'one'},{'id':'cross_owner','owner_id':'one'}])
        db.execute(metadata.tables['care_topic_encounters'].insert(),[
            {'topic_id':topic,'encounter_id':event,'owner_id':'one'} for topic,event in
            [('a','single'),('a','overlap'),('b','overlap'),('gone','deleted'),('foreign','cross_owner')]])
        module.op = Operations(MigrationContext.configure(db))
        module.upgrade()
        parents = dict(db.execute(sa.text('SELECT id,primary_topic_id FROM encounters')).all())
        assert parents == {'single':'a','overlap':None,'deleted':None,'cross_owner':None}
        assert db.scalar(sa.text('SELECT COUNT(*) FROM care_topic_encounters')) == 5
        module.downgrade()
        assert 'primary_topic_id' not in {column['name'] for column in sa.inspect(db).get_columns('encounters')}
    engine.dispose()
