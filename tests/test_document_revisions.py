import asyncio
from datetime import date
from uuid import UUID

from app.models import Document, LabResult, User
from tests.test_uploads import setup_admin


def test_archived_document_update_is_versioned_and_audited(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            row = Document(owner_id=user.id, document_type='检查报告', title='修改前',
                           patient_scope='unconfirmed', type_specific_data={})
            db.add(row); await db.commit(); return row.id
    document_id = asyncio.run(seed())
    changed = client.patch(f'/api/documents/{document_id}', json={
        'expected_version': 1, 'title': '修改后', 'patient_scope': 'self',
        'type_specific_data': {'exam': {'exam_name': 'MRI', 'findings': ['合成所见'], 'impression': []}},
    })
    assert changed.status_code == 200
    assert changed.json()['version'] == 2
    assert changed.json()['title'] == '修改后'
    stale = client.patch(f'/api/documents/{document_id}', json={'expected_version': 1, 'title': '冲突'})
    assert stale.status_code == 409
    history = client.get(f'/api/documents/{document_id}/revisions').json()['items']
    assert len(history) == 1
    assert history[0]['from_version'] == 1
    assert history[0]['snapshot']['title'] == '修改前'
    assert set(history[0]['changed_fields']) == {'title', 'patient_scope', 'type_specific_data'}


def test_document_update_rejects_null_required_fields_and_nonfinite_amount(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            row = Document(owner_id=UUID(owner['id']), document_type='医疗发票 / 收费单', title='合成票据')
            db.add(row); await db.commit(); return row.id
    document_id = asyncio.run(seed())
    assert client.patch(f'/api/documents/{document_id}', json={
        'expected_version': 1, 'title': None,
    }).status_code == 422
    assert client.patch(f'/api/documents/{document_id}', json={
        'expected_version': 1, 'amount': 'NaN',
    }).status_code == 422
    for field in ['document_type', 'key_information', 'patient_scope', 'type_specific_data']:
        assert client.patch(f'/api/documents/{document_id}', json={
            'expected_version': 1, field: None,
        }).status_code == 422


def test_document_receipt_update_keeps_cost_aggregation_in_sync(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        from decimal import Decimal
        from app.models import ReceiptDetail
        async with session_factory() as db:
            row = Document(owner_id=UUID(owner['id']), document_type='医疗发票 / 收费单', title='待修订票据',
                           amount=Decimal('10'), type_specific_data={'receipt': {'total_amount': '10.00', 'currency': 'CNY', 'line_items': []}})
            db.add(row); await db.flush()
            db.add(ReceiptDetail(owner_id=row.owner_id, document_id=row.id, total_amount=Decimal('10'), currency='CNY'))
            await db.commit(); return row.id
    document_id = asyncio.run(seed())
    changed = client.patch(f'/api/documents/{document_id}', json={
        'expected_version': 1,
        'type_specific_data': {'receipt': {'total_amount': '23.45', 'currency': 'CNY', 'line_items': []}},
    })
    assert changed.status_code == 200
    assert changed.json()['amount'] == '23.45'
    assert client.get('/api/costs/summary').json()['totals_by_currency'][0]['total'] == '23.45'
    split = client.patch(f'/api/documents/{document_id}', json={
        'expected_version': changed.json()['version'], 'amount': '30.00',
        'type_specific_data': {'receipt': {'total_amount': '30.00', 'insurance_amount': '12.00',
                                           'personal_amount': '18.00', 'currency': 'CNY', 'line_items': []}},
    })
    assert split.status_code == 200
    details = client.get(f'/api/documents/{document_id}').json()['receipt']
    assert details['insurance_amount'] == '12.00'
    assert details['personal_amount'] == '18.00'
    assert client.get('/api/costs/summary').json()['totals_by_currency'][0]['total'] == '30.00'


def test_confirming_archived_document_ownership_builds_existing_lab_trends(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            ids = []
            for day, value in [(1, '0.91'), (10, '0.95')]:
                doc = Document(owner_id=UUID(owner['id']), document_type='检验报告',
                               title=f'合成报告 {day}', primary_date=date(2026, 7, day),
                               patient_scope='unconfirmed')
                db.add(doc)
                await db.flush()
                db.add(LabResult(owner_id=doc.owner_id, document_id=doc.id,
                                 name='胱抑素 C', analyte_key='cystatin_c',
                                 result=value, unit='mg/L', result_type='numeric',
                                 review_status='confirmed'))
                ids.append(doc.id)
            await db.commit()
            return ids

    ids = asyncio.run(seed())
    before = client.get('/api/overview').json()
    assert before['ownership']['unconfirmed_documents'] == 2
    assert before['ownership']['unconfirmed_lab_results'] == 2
    assert not any(row['key'] == 'lab:cystatin_c' for row in before['metrics'])

    for doc_id in ids:
        updated = client.patch(f'/api/documents/{doc_id}', json={
            'expected_version': 1, 'patient_scope': 'self',
        })
        assert updated.status_code == 200

    after = client.get('/api/overview').json()
    assert after['ownership']['unconfirmed_documents'] == 0
    metric = next(row for row in after['metrics'] if row['key'] == 'lab:cystatin_c')
    assert metric['record_count'] == 2
    assert len(metric['trend_series'][0]['points']) == 2


def test_document_trash_hides_derived_data_and_restores_it(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        from decimal import Decimal
        from app.models import ReceiptDetail
        async with session_factory() as db:
            report = Document(owner_id=UUID(owner['id']), document_type='检验报告', title='本人血糖',
                              primary_date=date(2026, 9, 1), patient_scope='self')
            receipt = Document(owner_id=UUID(owner['id']), document_type='医疗发票 / 收费单', title='本人票据',
                               primary_date=date(2026, 9, 2), patient_scope='self', amount=Decimal('123.45'))
            db.add_all([report, receipt]); await db.flush()
            db.add(LabResult(owner_id=report.owner_id, document_id=report.id, name='空腹血糖',
                             analyte_key='glucose', result='5.6', unit='mmol/L', condition='空腹',
                             result_type='numeric', review_status='confirmed'))
            db.add(ReceiptDetail(owner_id=receipt.owner_id, document_id=receipt.id,
                                 total_amount=Decimal('123.45'), currency='CNY'))
            await db.commit()
            return str(report.id), str(receipt.id)
    report_id, receipt_id = asyncio.run(seed())
    assert client.get('/api/overview').json()['documents']['total'] == 2
    assert client.get('/api/costs/summary').json()['totals_by_currency'][0]['total'] == '123.45'
    assert any(row['key'] == 'fasting_glucose' and row['record_count'] == 1
               for row in client.get('/api/overview').json()['metrics'])

    for document_id in (report_id, receipt_id):
        removed = client.post(f'/api/documents/{document_id}/trash', json={'expected_version': 1})
        assert removed.status_code == 200
        assert removed.json()['deleted_at']
        assert client.post(f'/api/documents/{document_id}/trash', json={'expected_version': 1}).status_code == 409
    assert client.get('/api/overview').json()['documents']['total'] == 0
    assert client.get('/api/costs/summary').json()['receipts']['total'] == 0
    assert client.get('/api/documents').json()['items'] == []
    assert len(client.get('/api/documents/trash').json()['items']) == 2
    assert client.get('/api/documents/' + report_id).json()['lab_results'][0]['result'] == '5.6'
    assert client.get('/api/documents/' + report_id + '/revisions').json()['items'][0]['changed_fields'] == ['deleted_at']

    for document_id in (report_id, receipt_id):
        restored = client.post(f'/api/documents/{document_id}/restore', json={'expected_version': 2})
        assert restored.status_code == 200
        assert restored.json()['deleted_at'] is None
    assert client.get('/api/overview').json()['documents']['total'] == 2
    assert client.get('/api/costs/summary').json()['totals_by_currency'][0]['total'] == '123.45'
    assert any(row['key'] == 'fasting_glucose' and row['record_count'] == 1
               for row in client.get('/api/overview').json()['metrics'])


def test_correcting_confirmed_lab_result_updates_trend_and_keeps_revision(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            doc = Document(owner_id=UUID(owner['id']), document_type='检验报告', title='报告原件',
                           primary_date=date(2026, 9, 1), patient_scope='self')
            db.add(doc); await db.flush()
            lab = LabResult(owner_id=doc.owner_id, document_id=doc.id, name='空腹血糖',
                            analyte_key='glucose', result='5.6', unit='mmol/L', condition='空腹',
                            result_type='numeric', review_status='confirmed')
            db.add(lab); await db.commit()
            return str(doc.id), str(lab.id)
    document_id, lab_id = asyncio.run(seed())
    corrected = client.patch(f'/api/documents/{document_id}/lab-results/{lab_id}', json={
        'expected_document_version': 1, 'result': '4.8', 'reference_range': '3.9–6.1',
    })
    assert corrected.status_code == 200
    assert corrected.json()['version'] == 2
    assert client.patch(f'/api/documents/{document_id}/lab-results/{lab_id}', json={
        'expected_document_version': 1, 'result': '6.0',
    }).status_code == 409
    metric = next(row for row in client.get('/api/overview').json()['metrics'] if row['key'] == 'fasting_glucose')
    assert metric['latest_result'] == '4.8 mmol/L'
    assert client.get(f'/api/documents/{document_id}').json()['lab_results'][0]['result'] == '4.8'
    revision = client.get(f'/api/documents/{document_id}/revisions').json()['items'][0]
    assert revision['snapshot']['lab_result']['result'] == '5.6'
