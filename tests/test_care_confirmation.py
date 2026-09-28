import asyncio
import copy

from tests.test_confirmation import create_pending_draft
from tests.test_extraction import VALID_DRAFT
from tests.test_uploads import setup_admin
from app.models import Document
from app.services.batch_confirmation import historical_source


def test_historical_mention_only_uses_the_document_containing_its_text():
    unrelated = Document(title='报告甲', key_information=['本次复查结果'], parsed_content=None)
    source = Document(title='报告乙', key_information=['原文载明此前进行手术'], parsed_content=None)
    assert historical_source([unrelated, source], '此前进行手术') == (
        source, 'document.key_information.0')
    assert historical_source([unrelated], '此前进行手术') is None


def test_confirming_one_lab_report_immediately_creates_source_backed_event(client, session_factory):
    owner = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, owner['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['document']['primary_date_raw'] = '报告日期：2026-09-06'
    payload['document']['key_information'] = ['原报告载明阴性']
    result = client.post(f'/api/drafts/{draft_id}/confirm', json={'payload':payload})
    assert result.status_code == 201, result.text
    document_id = result.json()['document_id']
    event = client.get('/api/care-history').json()['recent'][0]
    assert event['event_kind'] == 'laboratory'
    assert event['date_basis'] == 'report'
    assert event['document_count'] == 1
    assert event['facts'][0]['text'] == '原报告载明阴性'
    assert event['facts'][0]['source_refs'][0]['document_id'] == document_id
    assert client.get(f"/api/care-history/events/{event['id']}").json()['documents'][0]['id'] == document_id
    assert client.post(f'/api/drafts/{draft_id}/confirm', json={'payload':payload}).status_code == 409
    assert client.get('/api/care-history').json()['summary']['event_count'] == 1


def test_report_without_date_is_visible_in_undated_area(client, session_factory):
    owner = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, owner['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['document']['primary_date'] = None
    payload['document']['primary_date_raw'] = None
    result = client.post(f'/api/drafts/{draft_id}/confirm', json={'payload':payload})
    assert result.status_code == 201, result.text
    overview = client.get('/api/care-history').json()
    assert overview['summary']['undated_count'] == 1
    event = client.get('/api/care-history/events?undated=true').json()['items'][0]
    assert event['date'] is None and event['date_basis'] == 'unknown'


def test_receipt_only_does_not_invent_visit(client, session_factory):
    owner = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, owner['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['document'].update({'type':'医疗发票 / 收费单','title':'合成收费票据','amount':'12.00元'})
    result = client.post(f'/api/drafts/{draft_id}/confirm', json={'payload':payload})
    assert result.status_code == 201, result.text
    assert client.get('/api/care-history').json()['summary']['event_count'] == 0
    assert client.get('/api/documents').json()['items'][0]['title'] == '合成收费票据'
