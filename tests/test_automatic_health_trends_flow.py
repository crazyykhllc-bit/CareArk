import asyncio
import copy

from tests.test_confirmation import create_pending_draft
from tests.test_extraction import VALID_DRAFT
from tests.test_uploads import setup_admin


def test_confirmed_ogtt_report_appears_in_overview_without_manual_setup(client, session_factory):
    owner = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, owner['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['document'].update({
        'title': '口服葡萄糖耐量试验', 'primary_date': '2026-07-10',
        'hospital': '示例医院', 'patient_scope': 'self',
    })
    payload['lab_results'] = [{
        'name': '葡萄糖', 'analyte_key': 'glucose', 'result': value, 'unit': 'mmol/L',
        'observed_date': '2026-07-10', 'timepoint_minutes': minute,
        'result_type': 'numeric', 'review_status': 'confirmed',
    } for minute, value in [(0, '4.98'), (30, '9.54'), (60, '6.43'), (120, '5.27'), (180, '4.11')]]

    confirmed = client.post(f'/api/drafts/{draft_id}/confirm', json={'payload': payload})
    overview = client.get('/api/overview').json()

    assert confirmed.status_code == 201
    metric = next(item for item in overview['metrics'] if item['key'] == 'ogtt_glucose')
    assert metric['record_count'] == 1
    assert metric['trend_axis'] == 'minutes'
    assert [point['x'] for point in metric['trend_series'][0]['points']] == [0, 30, 60, 120, 180]
    assert metric['latest_result'].startswith('0分钟 4.98 / 30分钟 9.54')
    assert client.get('/api/test-sessions/candidates').json()['items'] == []
