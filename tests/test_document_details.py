import asyncio
from decimal import Decimal
from uuid import UUID

from app.document_schemas import DocumentDetails, ReceiptDetails
from app.models import Document, ReceiptDetail, User
from app.schemas import DocumentDraft, LabResultDraft


def test_document_details_preserve_exam_and_receipt_zero_values():
    details = DocumentDetails.model_validate({
        'exam': {'exam_name': '头颅 MRI', 'findings': ['合成所见'], 'impression': ['合成意见']},
        'receipt': {'total_amount': '0', 'insurance_amount': None, 'personal_amount': '0.00',
                    'currency': 'CNY', 'line_items': [{'name': '合成项目', 'amount': '0'}]},
    })
    assert details.exam.findings == ['合成所见']
    assert details.receipt.total_amount == Decimal('0')
    assert details.receipt.insurance_amount is None
    assert details.receipt.personal_amount == Decimal('0.00')


def test_blank_and_nonfinite_receipt_amounts_are_unknown_or_rejected():
    receipt = ReceiptDetails.model_validate({'total_amount': '  ', 'currency': 'CNY'})
    assert receipt.total_amount is None
    yuan_receipt = ReceiptDetails.model_validate({'total_amount': '12元', 'currency': 'CNY'})
    assert yuan_receipt.total_amount == Decimal('12')
    for value in ['NaN', 'Infinity', '-Infinity', '12万元', '约12元']:
        try:
            ReceiptDetails.model_validate({'total_amount': value, 'currency': 'CNY'})
        except ValueError:
            continue
        raise AssertionError(f'{value} should not be accepted as an exact amount')

    try:
        ReceiptDetails.model_validate({'line_items': [{'name': '合成项目', 'quantity': '2元'}]})
    except ValueError:
        pass
    else:
        raise AssertionError('数量不能带货币单位')


def test_extraction_contract_carries_typed_details_and_lab_context():
    source_id = '00000000-0000-4000-8000-000000000001'
    document = DocumentDraft.model_validate({
        'type': '检查报告', 'title': '合成检查报告', 'patient_scope': 'other',
        'details': {'exam': {'exam_name': 'CT', 'findings': ['合成所见'], 'impression': []}},
    })
    lab = LabResultDraft.model_validate({
        'name': '葡萄糖', 'result': '5.0', 'unit': 'mmol/L', 'analyte_key': 'glucose',
        'specimen': '血清', 'condition': '空腹', 'observed_date': '2026-09-11',
        'timepoint_minutes': 0, 'test_session_key': 'ogtt-source-1', 'source_id': source_id,
        'result_type': 'numeric', 'review_status': 'confirmed',
    })
    assert document.patient_scope == 'other'
    assert document.details.exam.exam_name == 'CT'
    assert lab.condition == '空腹'
    assert lab.source_id == source_id


def test_document_detail_api_returns_typed_data_without_cross_user_access(client, session_factory):
    from tests.test_uploads import setup_admin
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            document = Document(owner_id=user.id, document_type='检查报告', title='合成影像报告',
                                patient_scope='self', type_specific_data={
                                    'exam': {'exam_name': 'MRI', 'findings': ['合成所见'], 'impression': ['合成意见']},
                                })
            db.add(document)
            await db.flush()
            db.add(ReceiptDetail(owner_id=user.id, document_id=document.id, total_amount=Decimal('0'),
                                 currency='CNY', line_items=[]))
            await db.commit()
            return document.id

    document_id = asyncio.run(seed())
    result = client.get(f'/api/documents/{document_id}')
    assert result.status_code == 200
    assert result.json()['patient_scope'] == 'self'
    assert result.json()['type_specific_data']['exam']['findings'] == ['合成所见']
    assert result.json()['receipt']['total_amount'] == '0.00'
