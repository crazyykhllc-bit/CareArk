import asyncio
from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.models import CareTopicEncounter, Document, Encounter, User
from app.services.care_suggestions import prepare_suggestions
from tests.test_uploads import setup_admin


def seed_records(factory, owner_id):
    async def run():
        async with factory() as db:
            owner = await db.get(User, UUID(owner_id))
            first = Encounter(owner_id=owner.id, title='合成住院事件', hospital='甲医院',
                date=date(2026, 1, 10), date_basis='admission', event_kind='inpatient',
                evidence=[], summary_facts=[], milestones=[])
            second = Encounter(owner_id=owner.id, title='合成复诊事件', hospital='乙医院',
                date=date(2026, 2, 2), date_basis='visit', event_kind='followup',
                evidence=[], summary_facts=[], milestones=[])
            db.add_all([first, second]); await db.flush()
            first_doc = Document(owner_id=owner.id, encounter_id=first.id, document_type='检查报告',
                title='检查甲', primary_date=date(2026, 1, 10), hospital='甲医院',
                key_information=['原报告所见甲'], patient_scope='self', type_specific_data={})
            second_doc = Document(owner_id=owner.id, encounter_id=first.id, document_type='检验报告',
                title='检验乙', primary_date=date(2026, 1, 11), hospital='甲医院',
                key_information=['原报告结果乙'], patient_scope='self', type_specific_data={})
            other_doc = Document(owner_id=owner.id, encounter_id=second.id, document_type='挂号单 / 就诊单',
                title='复诊单', primary_date=date(2026, 2, 2), hospital='乙医院',
                key_information=[], patient_scope='self', type_specific_data={})
            ungrouped = Document(owner_id=owner.id, document_type='检验报告', title='孤立检验',
                primary_date=date(2026, 3, 1), hospital='甲医院',
                key_information=['原文阴性'], patient_scope='self', type_specific_data={})
            db.add_all([first_doc, second_doc, other_doc, ungrouped]); await db.commit()
            return first.id, second.id, first_doc.id, ungrouped.id
    return asyncio.run(run())


def test_care_timeline_counts_events_and_preserves_source_documents(client, session_factory):
    owner = setup_admin(client)
    first, second, source, _ = seed_records(session_factory, owner['id'])
    overview = client.get('/api/care-history').json()
    assert overview['summary']['event_count'] == 2
    assert overview['summary']['hospital_count'] == 2
    events = {item['id']: item for item in overview['recent']}
    assert events[str(first)]['document_count'] == 2
    assert events[str(first)]['facts'][0]['source_refs'][0]['document_id'] in {
        str(source), *(str(item['id']) for item in client.get(f'/api/care-history/events/{first}').json()['documents'])}
    assert events[str(second)]['document_count'] == 1
    assert client.get('/api/care-history?hospital=乙医院').json()['summary']['event_count'] == 1
    assert client.get(f'/api/care-history/events/{first}').json()['documents'][0]['encounter_id'] == str(first)


def test_topics_are_editable_without_removing_events_or_documents(client, session_factory):
    owner = setup_admin(client)
    first, second, source, _ = seed_records(session_factory, owner['id'])
    made = client.post('/api/care-topics', json={'name':'跨院经历','event_ids':[str(first),str(second)]})
    assert made.status_code == 201, made.text
    topic = made.json()
    assert client.put(f"/api/care-topics/{topic['id']}/events/{first}", json={}).status_code == 200
    assert client.get(f"/api/care-topics/{topic['id']}").json()['event_count'] == 2
    changed = client.patch(f"/api/care-topics/{topic['id']}", json={'expected_version':topic['version'],'name':'跨院复诊'})
    assert changed.status_code == 200, changed.text
    assert client.patch(f"/api/care-topics/{topic['id']}", json={'expected_version':topic['version'],'name':'旧版本'}).status_code == 409
    removed = client.delete(f"/api/care-topics/{topic['id']}/events/{first}")
    assert removed.status_code == 200
    assert client.get(f'/api/care-history/events/{first}').status_code == 200
    assert client.get(f'/api/documents/{source}').status_code == 200
    trashed = client.post(f"/api/care-topics/{topic['id']}/trash", json={'expected_version':removed.json()['version']})
    assert trashed.status_code == 200
    assert client.get('/api/care-topics').json()['items'] == []
    restored = client.post(f"/api/care-topics/{topic['id']}/restore", json={'expected_version':trashed.json()['version']})
    assert restored.status_code == 200


def test_topic_matches_checked_titles_and_respects_manual_removal(client, session_factory):
    owner = setup_admin(client)
    first, second, _, _ = seed_records(session_factory, owner['id'])
    async def add_matched_document():
        async with session_factory() as db:
            db.add(Document(owner_id=UUID(owner['id']), encounter_id=first,
                document_type='检查报告', title='肺结节术前检查报告',
                hospital='甲医院', patient_scope='self', key_information=[], type_specific_data={}))
            await db.commit()
    asyncio.run(add_matched_document())
    topic = client.post('/api/care-topics', json={'name':'肺结节手术'}).json()
    assert topic['event_count'] == 1
    assert client.get(f"/api/care-topics/{topic['id']}").json()['events'][0]['id'] == str(first)
    async def provenance():
        async with session_factory() as db:
            return await db.scalar(select(CareTopicEncounter).where(
                CareTopicEncounter.topic_id == UUID(topic['id'])))
    assert asyncio.run(provenance()).origin == 'auto'
    assert client.delete(f"/api/care-topics/{topic['id']}/events/{first}").status_code == 200
    assert client.post('/api/care-topics/organize', json={}).json()['linked_events'] == 0
    assert client.get(f"/api/care-topics/{topic['id']}").json()['event_count'] == 0
    assert client.put(f"/api/care-topics/{topic['id']}/events/{first}", json={}).status_code == 200
    assert client.get(f"/api/care-topics/{topic['id']}").json()['event_count'] == 1
    assert client.get(f'/api/care-history/events/{second}').json()['topic_ids'] == []


def test_explicit_cross_event_relation_creates_reversible_topic(client, session_factory):
    owner = setup_admin(client)
    first, second, source, _ = seed_records(session_factory, owner['id'])
    linked = client.put(f'/api/documents/{source}/related-encounters/{second}', json={})
    assert linked.status_code == 200, linked.text
    topics = client.get('/api/care-topics').json()['items']
    assert len(topics) == 1
    assert topics[0]['origin'] == 'auto'
    hierarchy = client.get('/api/care-hierarchy').json()['items']
    assert len(hierarchy) == 1
    assert hierarchy[0]['event_count'] == 2
    assert {item['id'] for item in client.get(f"/api/care-topics/{topics[0]['id']}").json()['events']} == {str(first), str(second)}
    assert client.post('/api/care-topics/organize', json={}).json() == {'created_topics': 0, 'linked_events': 0}
    assert client.delete(f'/api/documents/{source}/related-encounters/{second}').status_code == 200
    assert client.get(f"/api/care-topics/{topics[0]['id']}").json()['event_count'] == 0
    trashed = client.post(f"/api/care-topics/{topics[0]['id']}/trash", json={'expected_version':topics[0]['version']})
    assert trashed.status_code == 200
    assert client.post('/api/care-topics/organize', json={}).json()['created_topics'] == 0
    assert client.get('/api/care-topics').json()['items'] == []


def test_explicit_small_upload_does_not_get_auto_reparented(client,session_factory):
    owner=setup_admin(client)
    first,second,source,_=seed_records(session_factory,owner['id'])
    async def mark_small():
        async with session_factory() as db:
            event=await db.get(Encounter,first)
            event.evidence=['user_care_mode:small']
            await db.commit()
    asyncio.run(mark_small())
    assert client.put(f'/api/documents/{source}/related-encounters/{second}',json={}).status_code==200
    assert client.get('/api/care-topics').json()['items']==[]
    assert client.get(f'/api/care-history/events/{first}').json()['primary_topic_id'] is None


def test_model_topic_review_requires_source_quote_and_caches_result(client, session_factory, monkeypatch):
    from app.services.topic_analysis import TopicAssessment, TopicDecision

    owner = setup_admin(client)
    first, second, _, _ = seed_records(session_factory, owner['id'])
    async def add_sources():
        async with session_factory() as db:
            direct = Document(owner_id=UUID(owner['id']), encounter_id=first,
                document_type='住院资料', title='手术记录', hospital='甲医院',
                key_information=['本次肺结节切除手术已完成'], patient_scope='self', type_specific_data={})
            historical = Document(owner_id=UUID(owner['id']), encounter_id=second,
                document_type='门诊记录', title='复诊单', hospital='乙医院',
                key_information=['既往于2025年肺结节切除手术'], patient_scope='self', type_specific_data={})
            db.add_all([direct, historical])
            await db.commit()
            return direct.id, historical.id
    direct_id, historical_id = asyncio.run(add_sources())
    topic = client.post('/api/care-topics', json={'name':'肺结节手术'}).json()
    assert topic['event_count'] == 0
    calls = []
    async def fake_request(self, *args, **kwargs):
        calls.append(args)
        return TopicAssessment(decisions=[
            TopicDecision(event_id=first, document_id=direct_id,
                quote='本次肺结节切除手术已完成', relation='direct', confidence='high'),
            TopicDecision(event_id=second, document_id=historical_id,
                quote='既往于2025年肺结节切除手术', relation='direct', confidence='high'),
        ])
    monkeypatch.setattr('app.services.topic_analysis.BatchExtractor._request', fake_request)
    analyzed = client.post(f"/api/care-topics/{topic['id']}/analyze", json={})
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()['linked_events'] == 1
    assert analyzed.json()['pending_suggestions'] == 1
    assert client.post(f"/api/care-topics/{topic['id']}/analyze", json={}).json()['cached'] is True
    assert len(calls) == 1
    assert client.post('/api/care-topics/organize', json={}).json()['linked_events'] == 0
    assert client.get(f"/api/care-topics/{topic['id']}").json()['event_count'] == 1
    suggestion = client.get('/api/care-suggestions').json()['items'][0]
    assert suggestion['kind'] == 'topic_membership'
    accepted = client.post(f"/api/care-suggestions/{suggestion['id']}/accept", json={
        'expected_version':suggestion['version']})
    assert accepted.status_code == 200, accepted.text
    assert client.get(f"/api/care-topics/{topic['id']}").json()['event_count'] == 2
    assert client.delete(f"/api/care-topics/{topic['id']}/events/{second}").status_code == 200
    assert client.post('/api/care-topics/organize', json={}).json()['linked_events'] == 0


def test_event_edit_source_validation_and_recoverable_trash(client, session_factory):
    owner = setup_admin(client)
    first, _, source, _ = seed_records(session_factory, owner['id'])
    bad = client.patch(f'/api/care-history/events/{first}', json={'expected_version':1,
        'summary_facts':[{'id':'x','text':'无来源','origin':'source'}]})
    assert bad.status_code == 422
    changed = client.patch(f'/api/care-history/events/{first}', json={'expected_version':1,
        'user_note':'个人补充', 'date':'2026-01-12'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['date_basis'] == 'user_confirmed'
    assert len(client.get(f'/api/care-history/events/{first}/revisions').json()['items']) == 1
    removed = client.post(f'/api/care-history/events/{first}/trash', json={'expected_version':2})
    assert removed.status_code == 200
    assert client.get(f'/api/care-history/events/{first}').status_code == 404
    assert client.get(f'/api/documents/{source}').status_code == 200
    restored = client.post(f'/api/care-history/events/{first}/restore', json={'expected_version':3})
    assert restored.status_code == 200
    assert client.get(f'/api/care-history/events/{first}').status_code == 200


def test_event_without_date_is_explicitly_undated(client):
    setup_admin(client)
    created = client.post('/api/care-history/events', json={'title':'合成待定日期事件'})
    assert created.status_code == 201, created.text
    assert created.json()['date_basis'] == 'unknown'
    assert created.json()['date_basis_label'] == '日期待核对'
    assert client.get('/api/care-history').json()['summary']['undated_count'] == 1
    updated = client.patch(f"/api/care-history/events/{created.json()['id']}", json={
        'expected_version':1,'date':'2026-09-01'})
    assert updated.status_code == 200, updated.text
    cleared = client.patch(f"/api/care-history/events/{created.json()['id']}", json={
        'expected_version':2,'date':None,'date_basis':'user_confirmed'})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()['date_basis'] == 'unknown'


def test_manual_event_does_not_merge_sources_from_different_hospitals(client, session_factory):
    owner = setup_admin(client)
    _, _, _, first_source = seed_records(session_factory, owner['id'])
    async def add_source():
        async with session_factory() as db:
            source = Document(owner_id=UUID(owner['id']), document_type='检验报告',
                title='另一医院报告', hospital='乙医院', patient_scope='self',
                key_information=[], type_specific_data={})
            db.add(source)
            await db.commit()
            return source.id
    second_source = asyncio.run(add_source())
    response = client.post('/api/care-history/events', json={
        'title':'错误跨院合并','document_ids':[str(first_source),str(second_source)]})
    assert response.status_code == 422
    assert client.get(f'/api/documents/{first_source}').json()['encounter_id'] is None
    assert client.get(f'/api/documents/{second_source}').json()['encounter_id'] is None


def test_source_revision_invalidates_old_excerpt_and_reflects_corrected_text(client, session_factory):
    owner = setup_admin(client)
    first, _, source, _ = seed_records(session_factory, owner['id'])
    excerpt = {'id':'checked-excerpt','text':'原报告所见甲','origin':'source',
        'source_refs':[{'document_id':str(source),'document_version':1,'quote':'原报告所见甲'}]}
    saved = client.patch(f'/api/care-history/events/{first}', json={'expected_version':1,'summary_facts':[excerpt]})
    assert saved.status_code == 200, saved.text
    assert saved.json()['facts'][0]['id'] == 'checked-excerpt'
    revised = client.patch(f'/api/documents/{source}', json={
        'expected_version':1,'key_information':['经核对后的原文甲']})
    assert revised.status_code == 200, revised.text
    detail = client.get(f'/api/care-history/events/{first}').json()
    assert all(item['id'] != 'checked-excerpt' for item in detail['facts'])
    assert any(item['text'] == '经核对后的原文甲' for item in detail['facts'])


def test_legacy_ungrouped_report_becomes_suggestion_until_accepted(client, session_factory):
    owner = setup_admin(client)
    _, _, _, ungrouped = seed_records(session_factory, owner['id'])
    async def prepare():
        async with session_factory() as db:
            return await prepare_suggestions(db, UUID(owner['id']), apply=True)
    assert asyncio.run(prepare())['created'] == 1
    assert asyncio.run(prepare())['created'] == 0
    assert client.get('/api/documents/' + str(ungrouped)).json()['encounter_id'] is None
    suggestion = client.get('/api/care-suggestions').json()['items'][0]
    accepted = client.post(f"/api/care-suggestions/{suggestion['id']}/accept", json={'expected_version':1})
    assert accepted.status_code == 200, accepted.text
    event_id = accepted.json()['result']['created_event_id']
    assert client.get('/api/documents/' + str(ungrouped)).json()['encounter_id'] == event_id
    assert client.get(f'/api/care-history/events/{event_id}').json()['date_basis'] == 'report'


def test_legacy_suggestion_can_be_corrected_before_acceptance(client, session_factory):
    owner = setup_admin(client)
    _, _, _, ungrouped = seed_records(session_factory, owner['id'])
    async def prepare():
        async with session_factory() as db:
            await prepare_suggestions(db, UUID(owner['id']), apply=True)
    asyncio.run(prepare())
    suggestion = client.get('/api/care-suggestions').json()['items'][0]
    accepted = client.post(f"/api/care-suggestions/{suggestion['id']}/accept", json={
        'expected_version':1,'title':'经核对的检查','date':'2026-03-02','date_basis':'examination'})
    assert accepted.status_code == 200, accepted.text
    event = client.get(f"/api/care-history/events/{accepted.json()['result']['created_event_id']}").json()
    assert event['title'] == '经核对的检查'
    assert event['date'] == '2026-03-02'
    assert event['date_basis'] == 'examination'
    assert event['date_sources'] == []
    assert event['documents'][0]['id'] == str(ungrouped)


def test_dismissed_suggestion_stays_hidden_until_its_source_changes(client, session_factory):
    owner = setup_admin(client)
    _, _, _, ungrouped = seed_records(session_factory, owner['id'])
    async def prepare():
        async with session_factory() as db:
            return await prepare_suggestions(db, UUID(owner['id']), apply=True)
    asyncio.run(prepare())
    suggestion = client.get('/api/care-suggestions').json()['items'][0]
    dismissed = client.post(f"/api/care-suggestions/{suggestion['id']}/dismiss", json={'expected_version':1})
    assert dismissed.status_code == 200
    assert asyncio.run(prepare())['created'] == 0
    assert client.get('/api/care-suggestions').json()['items'] == []
    async def revise():
        async with session_factory() as db:
            document = await db.get(Document, ungrouped)
            document.version += 1
            await db.commit()
    asyncio.run(revise())
    assert asyncio.run(prepare())['created'] == 1
    assert client.get('/api/care-suggestions').json()['items'][0]['version'] == 3


def test_care_events_and_topics_are_private_to_the_owner(client, app, session_factory):
    from fastapi.testclient import TestClient

    owner = setup_admin(client)
    first, _, _, _ = seed_records(session_factory, owner['id'])
    invitation = client.post('/api/admin/invitations', json={'email':'other-care@example.test'}).json()
    with TestClient(app) as other:
        registered = other.post('/api/auth/register/invitation', json={
            'token':invitation['token'],'password':'Correct-Horse-43'})
        assert registered.status_code == 201
        assert other.get(f'/api/care-history/events/{first}').status_code == 404
        assert other.post('/api/care-topics', json={'name':'不属于我的事件','event_ids':[str(first)]}).status_code == 422
    assert client.get(f'/api/care-history/events/{first}').status_code == 200


def test_recent_ten_and_older_month_do_not_repeat_the_boundary_events(client, session_factory):
    owner = setup_admin(client)
    async def seed():
        async with session_factory() as db:
            for index in range(12):
                db.add(Encounter(owner_id=UUID(owner['id']), title=f'合成事件 {index}',
                    hospital='合成医院', date=date(2026, 1, index+1),
                    date_basis='visit', event_kind='outpatient', evidence=[],
                    summary_facts=[], milestones=[]))
            await db.commit()
    asyncio.run(seed())
    overview = client.get('/api/care-history').json()
    assert len(overview['recent']) == 10
    assert overview['older_months'] == [{'month':'2026-01','count':2}]
    older = client.get('/api/care-history/events?month=2026-01&older=true').json()
    assert older['total'] == 2
    assert set(item['id'] for item in older['items']).isdisjoint(
        item['id'] for item in overview['recent'])
