import asyncio
import copy
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from app.services.storage import get_storage
from tests.test_e2e import png_bytes
from tests.test_uploads import FakeStorage, setup_admin


def create_batch(client, app, count=3):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    setup_admin(client)
    created = client.post('/api/batches', json={})
    assert created.status_code == 201
    batch = created.json()
    for i in range(count):
        response = client.post(f"/api/batches/{batch['id']}/files", data={'client_file_id': str(i)},
                               files={'file': (f'{i}.png', png_bytes(), 'image/png')})
        assert response.status_code == 201
    return client.get(f"/api/batches/{batch['id']}").json(), storage


def test_batch_limits_are_advertised_before_upload(client):
    setup_admin(client)
    response = client.get('/api/batches/limits')
    assert response.status_code == 200
    limits = response.json()
    assert limits['max_selection'] == 100
    assert limits['max_files_per_batch'] == 20
    assert limits['max_bytes_per_batch'] == 100 * 1024 * 1024
    assert limits['max_bytes_per_file'] == 25 * 1024 * 1024


def test_batch_upload_is_idempotent_and_waits_for_submit(client, app):
    batch, storage = create_batch(client, app)
    assert batch['status'] == 'receiving'
    assert len(batch['files']) == 3
    again = client.post(f"/api/batches/{batch['id']}/files", data={'client_file_id': '0'},
                        files={'file': ('0.png', png_bytes(), 'image/png')})
    assert again.status_code == 201
    assert len(storage.objects) == 3
    files = [x['id'] for x in batch['files']]
    response = client.post(f"/api/batches/{batch['id']}/submit", json={
        'expected_version': batch['version'], 'groups': [
            {'id': 'medicine-a', 'kind': 'medication', 'file_ids': files[:2], 'label': '药品 A'},
        ], 'encounters': [{'id': 'visit-a', 'file_ids': files, 'label': '一次就诊'}],
    })
    assert response.status_code == 200
    assert response.json()['status'] == 'queued'
    assert len(response.json()['grouping']['groups'][0]['file_ids']) == 2


def test_batch_rejects_foreign_group_files_and_stale_version(client, app):
    batch, _ = create_batch(client, app)
    url = f"/api/batches/{batch['id']}/submit"
    assert client.post(url, json={'expected_version': 0}).status_code == 409
    response = client.post(url, json={'expected_version': batch['version'], 'groups': [
        {'id': 'bad', 'kind': 'document', 'file_ids': ['00000000-0000-0000-0000-000000000000'], 'label': '错误'},
    ]})
    assert response.status_code == 422


def test_other_user_cannot_read_or_mutate_batch(client, app):
    batch, _ = create_batch(client, app)
    invite = client.post('/api/admin/invitations', json={'email': 'other@example.test'}).json()
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation', json={'token': invite['token'], 'password': 'Correct-Horse-43'})
        assert other.get(f"/api/batches/{batch['id']}").status_code == 404
        assert other.post(f"/api/batches/{batch['id']}/submit", json={'expected_version': batch['version']}).status_code == 404
        assert other.get('/api/batches').json()['items'] == []


def test_mixed_batch_process_review_confirm_keeps_documents_separate(client, app, session_factory):
    batch, storage = create_batch(client, app, 4)
    response = client.post(f"/api/batches/{batch['id']}/submit", json={'expected_version': batch['version']})
    assert response.status_code == 200
    from app.services.batch_jobs import BatchProcessor
    from app.batch_schemas import BatchExtraction
    from app.config import Settings

    class Extractor:
        async def extract_batch(self, sources, grouping):
            ids = [x['id'] for x in sources]
            return BatchExtraction.model_validate({'groups': [
                {'id': 'med-a', 'kind': 'medication', 'source_ids': ids[:2], 'document': {'type': '其他医疗资料', 'title': '药品 A 包装'},
                 'medications': [{'name': '药品 A', 'strength': '10mg', 'dosage_form': '片剂', 'manufacturer': '甲厂',
                                  'packages': [{'expiry_date': '2030-01-01', 'source_ids': ids[:1]}, {'expiry_date': '2031-01-01', 'source_ids': ids[1:2]}]}]},
                {'id': 'report', 'kind': 'document', 'source_ids': ids[2:3], 'encounter_id': 'visit',
                 'patient_identity': '童某',
                 'document': {'type': '检验报告', 'title': '报告', 'primary_date': '2026-09-06',
                              'hospital': '上海市肺科医院',
                              'patient_scope': 'unconfirmed'},
                 'lab_results': [{'name': '白细胞', 'result': '5.0', 'analyte_key': 'wbc', 'specimen': '全血',
                                  'condition': '空腹', 'observed_date': '2026-09-06', 'source_id': ids[2],
                                  'result_type': 'numeric', 'review_status': 'confirmed'}]},
                {'id': 'invoice', 'kind': 'document', 'source_ids': ids[3:4], 'encounter_id': 'visit',
                 'patient_identity': '董某',
                 'document': {'type': '医疗发票 / 收费单', 'title': '发票', 'amount': '12.30元',
                              'hospital': '上海市职业病防治医院',
                              'patient_scope': 'self', 'details': {'receipt': {
                                  'receipt_number': 'TEST-001', 'total_amount': '12.30元',
                                  'insurance_amount': None, 'personal_amount': '0元', 'currency': 'CNY',
                                  'line_items': [{'name': '合成项目', 'amount': '12.30元'}],
                              }}}},
            ], 'encounters': [{'id': 'visit', 'title': '门诊', 'hospital': '上海市职业病防治院',
                              'date': None, 'patient_identity': '益某'}]})

    processor = BatchProcessor(session_factory, storage, Extractor(), Settings())
    asyncio.run(processor.process(UUID(batch['id'])))
    draft = client.get(f"/api/batches/{batch['id']}/draft").json()
    assert len(draft['sources']) == 4
    assert client.get('/api/documents').json()['items'] == []
    payload = copy.deepcopy(draft['payload'])
    payload['groups'][0]['source_ids'] = ['invalid-source']
    assert client.put(f"/api/batches/{batch['id']}/draft", json={'expected_version': draft['version'], 'payload': payload}).status_code == 422
    payload = draft['payload']
    payload['reviewed'] = True
    saved = client.put(f"/api/batches/{batch['id']}/draft", json={'expected_version': draft['version'], 'payload': payload})
    assert saved.status_code == 200
    confirm_data = {'expected_version': saved.json()['version']}
    result = client.post(f"/api/batches/{batch['id']}/confirm", json=confirm_data)
    assert result.status_code == 200, result.text
    assert client.post(f"/api/batches/{batch['id']}/confirm", json=confirm_data).json() == result.json()
    docs = client.get('/api/documents').json()['items']
    assert len(docs) == 3
    assert len({d['encounter_id'] for d in docs if d['encounter_id']}) == 1
    assert client.get('/api/encounters').json()['items'][0]['date'] is None
    assert client.get('/api/overview').json()['hospitals'] == 1
    med = client.get('/api/medications').json()['items'][0]
    assert len(med['packages']) == 2
    assert med['status'] == '备用药'
    package_doc = next(d for d in docs if d['title'] == '药品 A 包装')
    detail = client.get(f"/api/documents/{package_doc['id']}").json()
    assert len(detail['attachments']) == 2
    assert package_doc['primary_date'] is None
    report_detail = client.get(f"/api/documents/{next(d['id'] for d in docs if d['title'] == '报告')}").json()
    assert report_detail['extraction_metadata']['patient_identity'] == '童某'
    assert report_detail['extraction_metadata']['model_patient_scope'] == 'unconfirmed'
    assert report_detail['patient_scope'] == 'self'
    unlinked = client.patch(f"/api/documents/{report_detail['id']}/encounter", json={
        'expected_version': report_detail['version'], 'encounter_id': None})
    assert unlinked.status_code == 200
    relinked = client.patch(f"/api/documents/{report_detail['id']}/encounter", json={
        'expected_version': unlinked.json()['version'], 'encounter_id': report_detail['encounter_id']})
    assert relinked.status_code == 200, relinked.text
    assert report_detail['lab_results'][0]['condition'] == '空腹'
    assert report_detail['lab_results'][0]['source_id'] == draft['sources'][2]['id']
    metric = next(item for item in client.get('/api/overview').json()['metrics'] if item['key'] == 'lab:wbc')
    assert metric['record_count'] == 1
    assert metric['trend_series'][0]['points'] == [{'x': '2026-09-06', 'y': '5.0'}]
    invoice_detail = client.get(f"/api/documents/{next(d['id'] for d in docs if d['title'] == '发票')}").json()
    assert invoice_detail['extraction_metadata']['patient_identity'] == '董某'
    assert invoice_detail['patient_scope'] == 'self'
    assert invoice_detail['receipt']['total_amount'] == '12.30'
    assert invoice_detail['receipt']['insurance_amount'] is None
    assert invoice_detail['receipt']['personal_amount'] == '0.00'
    from io import BytesIO
    from zipfile import ZipFile
    import json
    exported = client.get('/api/export')
    with ZipFile(BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['schema_version'] == 'health_archive_export.v5'
        assert len(manifest['document_sources']) == 4
        assert len(manifest['medication_packages']) == 2
        assert len(manifest['encounters']) == 1
    assert len([n for n in archive.namelist() if n.startswith('attachments/')]) == 4


def test_worker_provisionally_groups_nameless_drug_face_but_preserves_model_output(client, app, session_factory):
    batch, storage = create_batch(client, app, 3)
    assert client.post(f"/api/batches/{batch['id']}/submit", json={'expected_version': batch['version']}).status_code == 200
    from app.services.batch_jobs import BatchProcessor
    from app.batch_schemas import BatchExtraction
    from app.config import Settings
    from app.models import UploadBatch

    class Extractor:
        async def extract_batch(self, sources, grouping):
            ids = [source['id'] for source in sources]
            return BatchExtraction.model_validate({'groups': [
                {'id': 'named', 'kind': 'medication', 'source_ids': [ids[0], ids[2]],
                 'document': {'type': '其他医疗资料', 'title': '甲药包装'},
                 'medications': [{'name': '甲药', 'packages': [{'quantity_raw': '30片', 'source_ids': [ids[0], ids[2]]}]}]},
                {'id': 'bottom', 'kind': 'medication', 'source_ids': [ids[1]],
                 'document': {'type': '其他医疗资料', 'title': '待核对药品包装'},
                 'medications': [{'name': '待核对药品', 'packages': [
                     {'batch_number': 'B42', 'source_ids': [ids[1]]}]}]},
            ]})

    asyncio.run(BatchProcessor(session_factory, storage, Extractor(), Settings()).process(UUID(batch['id'])))
    draft = client.get(f"/api/batches/{batch['id']}/draft").json()
    assert len(draft['payload']['groups']) == 1
    assert len(draft['payload']['groups'][0]['source_ids']) == 3

    async def read_original():
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            return row.original_payload

    assert len(asyncio.run(read_original())['groups']) == 2


def test_receiving_grouping_is_saved_and_failed_batch_can_be_adjusted(client, app, session_factory):
    batch, _ = create_batch(client, app)
    grouping = {'expected_version': batch['version'], 'groups': [
        {'id': 'report', 'kind': 'document', 'label': '报告', 'file_ids': [x['id'] for x in batch['files'][:2]]}], 'encounters': []}
    saved = client.put(f"/api/batches/{batch['id']}/grouping", json=grouping)
    assert saved.status_code == 200
    assert saved.json()['grouping']['groups'][0]['label'] == '报告'
    from app.models import UploadBatch
    async def fail():
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            row.status = 'failed'
            await db.commit()
    asyncio.run(fail())
    reopened = client.post(f"/api/batches/{batch['id']}/reopen")
    assert reopened.status_code == 200
    assert reopened.json()['status'] == 'receiving'
    assert len(reopened.json()['files']) == 3


def test_expired_batch_lease_is_reclaimed_once(client, app, session_factory):
    batch, storage = create_batch(client, app, 1)
    submitted = client.post(f"/api/batches/{batch['id']}/submit", json={'expected_version': batch['version']})
    assert submitted.status_code == 200

    from app.models import UploadBatch
    from app.services.batch_jobs import BatchProcessor
    from app.config import Settings

    async def arrange_and_claim():
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            row.status = 'extracting'
            row.attempt_token = 'abandoned-attempt'
            row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        processor = BatchProcessor(session_factory, storage, object(), Settings())
        first = await processor.claim_next()
        second = await processor.claim_next()
        return first, second

    first, second = asyncio.run(arrange_and_claim())
    assert first[0] == UUID(batch['id'])
    assert first[1] != 'abandoned-attempt'
    assert second is None


def test_stale_batch_attempt_cannot_overwrite_new_lease(client, app, session_factory):
    batch, storage = create_batch(client, app, 1)
    submitted = client.post(f"/api/batches/{batch['id']}/submit", json={'expected_version': batch['version']})
    assert submitted.status_code == 200

    from app.models import UploadBatch
    from app.services.batch_jobs import BatchProcessor
    from app.config import Settings

    class CountingExtractor:
        calls = 0
        async def extract_batch(self, sources, grouping):
            self.calls += 1
            raise AssertionError('stale worker must not invoke model')

    async def arrange_and_process():
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            row.status = 'preprocessing'
            row.attempt_token = 'new-attempt'
            row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)
            await db.commit()
        extractor = CountingExtractor()
        await BatchProcessor(session_factory, storage, extractor, Settings()).process(batch['id'], 'old-attempt')
        async with session_factory() as db:
            row = await db.get(UploadBatch, UUID(batch['id']))
            return extractor.calls, row.status, row.attempt_token

    assert asyncio.run(arrange_and_process()) == (0, 'preprocessing', 'new-attempt')


def test_stale_batch_draft_update_is_rejected(client, app, session_factory):
    batch, storage = create_batch(client, app, 1)
    assert client.post(f"/api/batches/{batch['id']}/submit", json={'expected_version': batch['version']}).status_code == 200
    from app.services.batch_jobs import BatchProcessor
    from app.batch_schemas import BatchExtraction
    from app.config import Settings

    class Extractor:
        async def extract_batch(self, sources, grouping):
            return BatchExtraction.model_validate({'groups': [{
                'id': 'doc', 'kind': 'document', 'source_ids': [sources[0]['id']],
                'document': {'type': '其他医疗资料', 'title': '测试资料'},
            }]})

    asyncio.run(BatchProcessor(session_factory, storage, Extractor(), Settings()).process(UUID(batch['id'])))
    draft = client.get(f"/api/batches/{batch['id']}/draft").json()
    response = client.put(f"/api/batches/{batch['id']}/draft", json={
        'expected_version': draft['version'] - 1, 'payload': draft['payload'],
    })
    assert response.status_code == 409
