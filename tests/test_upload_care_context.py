import asyncio
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models import Attachment, CareTopic, CareTopicEncounter, Document, Encounter, SourceUnit, UploadBatch
from app.batch_schemas import BatchExtraction
from fastapi.testclient import TestClient
from tests.test_uploads import setup_admin


def ready(session_factory, owner, batch, hospital='合成甲医院', medication=False, linked=False):
    async def seed():
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            attachment = Attachment(owner_id=UUID(owner), filename='synthetic.png', mime_type='image/png', size_bytes=1,
                                    sha256='0'*64, object_key=str(uuid4()))
            db.add(attachment)
            await db.flush()
            source = SourceUnit(owner_id=UUID(owner), batch_id=row.id, attachment_id=attachment.id,
                                ordinal=0, label='synthetic', kind='image')
            db.add(source)
            await db.flush()
            group = {'id':'g', 'kind':'medication' if medication else 'document', 'source_ids':[str(source.id)],
                     'document':{'type':'其他医疗资料', 'title':'合成资料', 'hospital':hospital}}
            if medication:
                group['medications'] = [{'name':'合成药品'}]
            if linked:
                group['encounter_id'] = 'visit'
            row.payload = {'groups':[group], 'encounters':[{'id':'visit','title':'合成就诊','hospital':hospital}] if linked else [],
                           'excluded_sources':[], 'reviewed':True}
            row.status = 'pending_confirmation'
            await db.commit()
    asyncio.run(seed())
    return batch


def create(client, context):
    response = client.post('/api/batches', json={'care_context':context})
    assert response.status_code == 201, response.text
    return response.json()


def test_shared_intent_defers_parent_and_confirm_retries_keep_distinct_children(client, session_factory):
    owner = setup_admin(client)['id']
    context = {'intent_key':str(uuid4()), 'mode':'new_topic', 'name':'合成连续诊疗'}
    first, second = create(client, context), create(client, context)
    assert first.get('care_context', {}).get('intent_key') == context['intent_key']
    assert client.get('/api/care-hierarchy').json()['total'] == 0
    results = []
    for batch, hospital in [(first,'合成甲医院'), (second,'合成乙医院')]:
        ready(session_factory, owner, batch, hospital, linked=True)
        url = f"/api/batches/{batch['id']}/confirm"
        response = client.post(url, json={'expected_version':batch['version']})
        assert response.status_code == 200, response.text
        assert client.post(url, json={'expected_version':batch['version']}).json() == response.json()
        results.append(response.json())
    topics = client.get('/api/care-hierarchy?kind=topic').json()['items']
    assert len(topics) == 1
    detail = client.get(f"/api/care-topics/{topics[0]['id']}/overview").json()
    assert detail['event_count'] == 2 and detail['hospital_count'] == 2 and detail['document_count'] == 2
    assert results[0]['encounter_ids'] != results[1]['encounter_ids']


def test_unlinked_medication_never_creates_parent_or_encounter(client, session_factory):
    owner = setup_admin(client)['id']
    batch = create(client, {'intent_key':str(uuid4()),'mode':'new_topic','name':'不应创建的过程'})
    ready(session_factory, owner, batch, medication=True)
    response = client.post(f"/api/batches/{batch['id']}/confirm", json={'expected_version':batch['version']})
    assert response.status_code == 200, response.text
    assert client.get('/api/care-hierarchy').json()['total'] == 0


def test_archive_has_no_encounter_even_when_model_suggests_visit(client, session_factory):
    owner = setup_admin(client)['id']
    batch = create(client, {'intent_key':str(uuid4()),'mode':'archive'})
    ready(session_factory, owner, batch, linked=True)
    response = client.post(f"/api/batches/{batch['id']}/confirm", json={'expected_version':batch['version']})
    assert response.status_code == 200, response.text
    assert response.json()['encounter_ids'] == []
    assert client.get('/api/care-hierarchy').json()['total'] == 0


def test_pending_target_prevents_downgrade(client, session_factory):
    owner = setup_admin(client)['id']
    async def seed():
        async with session_factory() as db:
            event = Encounter(owner_id=UUID(owner), title='合成小事件')
            db.add(event)
            await db.commit()
            return str(event.id)
    event = asyncio.run(seed())
    topic = client.post(f'/api/care-history/events/{event}/upgrade',json={'expected_version':1,'name':'合成过程'}).json()
    create(client, {'intent_key':str(uuid4()),'mode':'existing_topic','topic_id':topic['topic_id']})
    response = client.post(f"/api/care-topics/{topic['topic_id']}/downgrade",json={'expected_version':topic['topic_version']})
    assert response.status_code == 409, response.text


def test_unknown_or_recycled_targets_rejected_and_shared_intent_cannot_change(client, session_factory):
    owner = setup_admin(client)['id']
    assert client.post('/api/batches',json={'care_context':{'intent_key':str(uuid4()),'mode':'existing_topic','topic_id':str(uuid4())}}).status_code == 404
    context = {'intent_key':str(uuid4()),'mode':'new_topic','name':'固定过程'}
    create(client, context)
    response = client.post('/api/batches',json={'care_context':{**context,'mode':'archive'}})
    assert response.status_code == 409


def test_existing_event_supplement_accepts_reviewed_cross_hospital_documents(client, session_factory):
    owner = setup_admin(client)['id']
    async def seed():
        async with session_factory() as db:
            event = Encounter(owner_id=UUID(owner),title='已有事件',hospital='合成甲医院')
            db.add(event)
            await db.commit()
            return str(event.id)
    event = asyncio.run(seed())
    context = {'intent_key':str(uuid4()),'mode':'existing_event','event_id':event}
    batch = create(client, context)
    ready(session_factory, owner, batch, linked=True)
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':batch['version']})
    assert response.status_code == 200, response.text
    assert response.json()['encounter_ids'] == [event]
    detail = client.get(f'/api/care-history/events/{event}').json()
    assert detail['document_count'] == 1 and detail['version'] > 1
    bad = create(client, {**context,'intent_key':str(uuid4())})
    ready(session_factory, owner, bad, '合成乙医院', linked=True)
    assert client.post(f"/api/batches/{bad['id']}/confirm",json={'expected_version':bad['version']}).status_code == 200
    assert client.get(f'/api/care-history/events/{event}').json()['document_count'] == 2


def test_foreign_and_deleted_targets_rejected_at_create_and_confirm(client, app, session_factory):
    owner = setup_admin(client)['id']
    invite = client.post('/api/admin/invitations', json={'email':'context-other@example.test'}).json()
    async def seed():
        async with session_factory() as db:
            topic = CareTopic(owner_id=UUID(owner),name='合成父级')
            db.add(topic)
            await db.commit()
            return str(topic.id)
    topic = asyncio.run(seed())
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation',json={'token':invite['token'],'password':'Correct-Horse-43'})
        assert other.post('/api/batches',json={'care_context':{'intent_key':str(uuid4()),'mode':'existing_topic','topic_id':topic}}).status_code == 404
    batch = create(client, {'intent_key':str(uuid4()),'mode':'existing_topic','topic_id':topic})
    ready(session_factory, owner, batch, linked=True)
    async def recycle():
        from app.models import utcnow
        async with session_factory() as db:
            row = await db.get(CareTopic, UUID(topic))
            row.deleted_at = utcnow()
            await db.commit()
    asyncio.run(recycle())
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':batch['version']})
    assert response.status_code == 404
    assert client.get('/api/documents').json()['items'] == []


def test_review_group_override_archive_does_not_change_shared_intent(client, session_factory):
    owner = setup_admin(client)['id']
    batch = create(client, {'intent_key':str(uuid4()),'mode':'new_topic','name':'合成父级'})
    ready(session_factory, owner, batch, linked=True)
    draft = client.get(f"/api/batches/{batch['id']}/draft").json()
    saved = client.put(f"/api/batches/{batch['id']}/draft",json={'expected_version':batch['version'],
        'payload':draft['payload'],'care_targets':{'g':{'mode':'archive'}}})
    assert saved.status_code == 200, saved.text
    assert saved.json()['care_context']['mode'] == 'new_topic'
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':saved.json()['version']})
    assert response.status_code == 200
    assert client.get('/api/care-hierarchy').json()['total'] == 0


def test_cancelled_upload_has_no_parent_and_is_removed_from_pending_tasks(client):
    setup_admin(client)
    batch = create(client, {'intent_key':str(uuid4()),'mode':'new_topic','name':'不应创建'})
    response = client.post(f"/api/batches/{batch['id']}/cancel",json={'expected_version':batch['version']})
    assert response.status_code == 200
    assert response.json()['status'] == 'cancelled'
    assert client.get('/api/batches').json()['items'] == []
    assert client.get('/api/care-hierarchy').json()['total'] == 0


def test_upload_context_export_keeps_batch_intent_relationship(client, app):
    import json
    from io import BytesIO
    from zipfile import ZipFile
    from app.services.storage import get_storage
    from tests.test_uploads import FakeStorage
    setup_admin(client)
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    batch = create(client, {'intent_key':str(uuid4()),'mode':'new_topic','name':'合成过程'})
    response = client.get('/api/export')
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    assert manifest['batches'][0]['care_context_id'] == batch['care_context']['id']
    assert manifest['upload_care_contexts'][0]['intent_key'] == batch['care_context']['intent_key']


def test_archive_ignores_model_visit_hospital_conflict(client, session_factory):
    owner = setup_admin(client)['id']
    batch = create(client, {'intent_key':str(uuid4()),'mode':'archive'})
    ready(session_factory, owner, batch, linked=True)
    async def conflict():
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            import copy
            payload = copy.deepcopy(row.payload)
            other = copy.deepcopy(payload['groups'][0])
            other['id']='other'
            other['document']['hospital']='合成乙医院'
            payload['groups'].append(other)
            row.payload = payload
            await db.commit()
    asyncio.run(conflict())
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':batch['version']})
    assert response.status_code == 200, response.text
    assert client.get('/api/care-hierarchy').json()['total'] == 0


def test_reviewed_existing_visit_preserves_each_document_hospital(client, session_factory):
    owner = setup_admin(client)['id']
    batch = create(client, {'intent_key':str(uuid4()),'mode':'new_topic','name':'跨院诊疗过程'})
    ready(session_factory, owner, batch, '合成乙医院', linked=True)
    async def link():
        import copy
        async with session_factory() as db:
            event = Encounter(owner_id=UUID(owner),title='已有甲医院就诊',hospital='合成甲医院')
            db.add(event)
            await db.flush()
            row = await db.get(UploadBatch, UUID(batch['id']))
            payload = copy.deepcopy(row.payload)
            payload['encounters'][0].update(hospital=None,existing_encounter_id=str(event.id))
            row.payload = payload
            await db.commit()
    asyncio.run(link())
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':batch['version']})
    assert response.status_code == 200, response.text
    assert client.get('/api/care-hierarchy?kind=topic').json()['total'] == 1
    assert client.get('/api/documents').json()['items'][0]['hospital'] == '合成乙医院'


def test_upload_does_not_move_existing_child_to_different_parent_silently(client, session_factory):
    owner = setup_admin(client)['id']
    async def seed():
        async with session_factory() as db:
            topic = CareTopic(owner_id=UUID(owner),name='原过程')
            db.add(topic)
            await db.flush()
            event = Encounter(owner_id=UUID(owner),title='原诊疗',hospital='合成甲医院',primary_topic_id=topic.id)
            db.add(event)
            await db.flush()
            db.add(CareTopicEncounter(owner_id=UUID(owner),topic_id=topic.id,encounter_id=event.id,origin='manual'))
            await db.commit()
            return str(event.id),str(topic.id)
    event, original = asyncio.run(seed())
    batch = create(client, {'intent_key':str(uuid4()),'mode':'new_topic','name':'新过程'})
    ready(session_factory, owner, batch, linked=True)
    async def link():
        import copy
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            payload = copy.deepcopy(row.payload)
            payload['encounters'][0]['existing_encounter_id']=event
            row.payload=payload
            await db.commit()
    asyncio.run(link())
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':batch['version']})
    assert response.status_code == 409, response.text
    assert client.get(f'/api/care-history/events/{event}').json()['primary_topic_id'] == original
    assert client.get('/api/care-hierarchy?kind=topic').json()['total'] == 1


def test_review_can_redirect_group_after_original_target_recycled(client, session_factory):
    owner = setup_admin(client)['id']
    async def seed():
        async with session_factory() as db:
            topic = CareTopic(owner_id=UUID(owner),name='原过程')
            db.add(topic)
            await db.commit()
            return str(topic.id)
    topic = asyncio.run(seed())
    batch = create(client, {'intent_key':str(uuid4()),'mode':'existing_topic','topic_id':topic})
    ready(session_factory, owner, batch, linked=True)
    async def recycle():
        from app.models import utcnow
        async with session_factory() as db:
            row = await db.get(CareTopic, UUID(topic))
            row.deleted_at=utcnow()
            await db.commit()
    asyncio.run(recycle())
    draft = client.get(f"/api/batches/{batch['id']}/draft").json()
    saved = client.put(f"/api/batches/{batch['id']}/draft",json={'expected_version':batch['version'],
        'payload':draft['payload'],'care_targets':{'g':{'mode':'small'}}})
    assert saved.status_code == 200
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':saved.json()['version']})
    assert response.status_code == 200, response.text
    assert client.get('/api/care-hierarchy').json()['items'][0]['item_type'] == 'event'


def test_released_small_event_can_receive_supplement_after_parent_trash(client, session_factory):
    from app.models import utcnow
    owner = setup_admin(client)['id']
    async def seed():
        async with session_factory() as db:
            topic = CareTopic(owner_id=UUID(owner),name='已回收过程',deleted_at=utcnow())
            db.add(topic)
            await db.flush()
            event = Encounter(owner_id=UUID(owner),title='恢复独立展示的事件',hospital='合成甲医院',primary_topic_id=topic.id)
            db.add(event)
            await db.commit()
            return str(event.id)
    event = asyncio.run(seed())
    batch = create(client, {'intent_key':str(uuid4()),'mode':'existing_event','event_id':event})
    ready(session_factory, owner, batch, linked=True)
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':batch['version']})
    assert response.status_code == 200, response.text
    assert response.json()['encounter_ids'] == [event]


def test_small_upload_shared_intent_keeps_one_event_across_batches(client, session_factory):
    owner = setup_admin(client)['id']
    context = {'intent_key':str(uuid4()), 'mode':'small', 'name':'一次完整看病'}
    first = create(client, context)
    ready(session_factory, owner, first, '合成甲医院', linked=True)
    result1 = client.post(f"/api/batches/{first['id']}/confirm",json={'expected_version':first['version']})
    assert result1.status_code == 200, result1.text
    second = create(client, context)
    ready(session_factory, owner, second, '合成乙医院', linked=False)
    result2 = client.post(f"/api/batches/{second['id']}/confirm",json={'expected_version':second['version']})
    assert result2.status_code == 200, result2.text
    assert result1.json()['encounter_ids'] == result2.json()['encounter_ids']
    assert client.get('/api/care-hierarchy').json()['total'] == 1
    event_id = result1.json()['encounter_ids'][0]
    documents = client.get(f'/api/care-history/events/{event_id}').json()['documents']
    assert len(documents) == 2
    assert {d['hospital'] for d in documents} == {'合成甲医院','合成乙医院'}


def test_many_report_groups_are_saved_as_one_user_chosen_small_event(client, session_factory):
    owner = setup_admin(client)['id']
    batch = create(client, {'intent_key':str(uuid4()),'mode':'small','name':'合成完整就诊'})
    ready(session_factory, owner, batch, linked=True)
    async def add():
        import copy
        async with session_factory() as db:
            row = await db.get(UploadBatch,UUID(batch['id']))
            payload = copy.deepcopy(row.payload)
            payload['groups'].append({**copy.deepcopy(payload['groups'][0]),'id':'g2','encounter_id':None})
            payload['groups'][1]['document'].update(title='合成收费单',hospital='合成乙医院')
            row.payload = payload
            await db.commit()
    asyncio.run(add())
    response = client.post(f"/api/batches/{batch['id']}/confirm",json={'expected_version':batch['version']})
    assert response.status_code == 200,response.text
    assert len(response.json()['document_ids']) == 2
    assert len(response.json()['encounter_ids']) == 1
    event_id = response.json()['encounter_ids'][0]
    detail = client.get(f'/api/care-history/events/{event_id}').json()
    assert detail['title'] == '合成完整就诊'
    assert detail['document_count'] == 2
    assert {d['hospital'] for d in detail['documents']} == {'合成甲医院','合成乙医院'}
    assert client.get('/api/care-hierarchy?hospital=合成乙医院').json()['total'] == 1
    assert detail['hospital_count'] == 2


def test_review_can_change_small_batch_to_new_big_event_without_changing_siblings(client, session_factory):
    owner = setup_admin(client)['id']
    original = {'intent_key':str(uuid4()), 'mode':'small', 'name':'原小事件'}
    batch, sibling = create(client, original), create(client, original)
    ready(session_factory, owner, batch, linked=True)
    draft = client.get(f"/api/batches/{batch['id']}/draft").json()
    new_intent = {'intent_key':str(uuid4()), 'mode':'new_topic', 'name':'合成术后随访'}
    response = client.put(f"/api/batches/{batch['id']}/draft", json={
        'expected_version':draft['version'], 'payload':draft['payload'], 'care_context':new_intent, 'care_targets':{}})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['care_context']['mode'] == 'new_topic'
    assert saved['care_context']['id'] != draft['care_context']['id']
    assert BatchExtraction.model_validate(saved['payload']) == BatchExtraction.model_validate(draft['payload'])
    assert client.get(f"/api/batches/{sibling['id']}").json()['care_context']['mode'] == 'small'
    assert client.get('/api/care-hierarchy').json()['total'] == 0
    url = f"/api/batches/{batch['id']}/confirm"
    response = client.post(url, json={'expected_version':saved['version']})
    assert response.status_code == 200, response.text
    assert client.post(url, json={'expected_version':saved['version']}).json() == response.json()
    topics = client.get('/api/care-hierarchy?kind=topic').json()['items']
    assert len(topics) == 1 and topics[0]['name'] == '合成术后随访'


def test_review_batch_target_rejects_invalid_existing_event_and_keeps_draft(client, session_factory):
    owner = setup_admin(client)['id']
    batch = create(client, {'intent_key':str(uuid4()), 'mode':'small'})
    ready(session_factory, owner, batch)
    url = f"/api/batches/{batch['id']}/draft"
    draft = client.get(url).json()
    response = client.put(url, json={'expected_version':draft['version'], 'payload':draft['payload'],
        'care_context':{'intent_key':str(uuid4()),'mode':'existing_event','event_id':str(uuid4())},'care_targets':{}})
    assert response.status_code == 404
    unchanged = client.get(url).json()
    assert unchanged['version'] == draft['version'] and unchanged['care_context'] == draft['care_context']
