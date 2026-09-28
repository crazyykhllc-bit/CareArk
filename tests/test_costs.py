import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models import Document, ReceiptDetail, User
from app.document_schemas import ReceiptDetails
from tests.test_uploads import setup_admin


def test_currency_aliases_are_grouped_with_existing_receipts(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            docs = [Document(owner_id=user.id, document_type='医疗发票 / 收费单',
                             title=f'票据 {index}', primary_date=date(2026, 9, 24))
                    for index in range(3)]
            db.add_all(docs)
            await db.flush()
            db.add_all([
                ReceiptDetail(owner_id=user.id, document_id=docs[0].id,
                              total_amount=Decimal('402.40'), currency='CNY'),
                ReceiptDetail(owner_id=user.id, document_id=docs[1].id,
                              total_amount=Decimal('378.40'), currency='人民币'),
                ReceiptDetail(owner_id=user.id, document_id=docs[2].id,
                              total_amount=Decimal('10.00'), currency='USD'),
            ])
            await db.commit()
    asyncio.run(seed())

    summary = client.get('/api/costs/summary').json()
    assert summary['totals_by_currency'] == [
        {'currency': 'CNY', 'total': '780.80', 'known_count': 2, 'unknown_count': 0},
        {'currency': 'USD', 'total': '10.00', 'known_count': 1, 'unknown_count': 0},
    ]
    assert [entry['currency'] for entry in summary['years'][0]['totals']] == ['CNY', 'USD']
    assert {item['currency'] for item in client.get('/api/costs/receipts').json()['items']} == {'CNY', 'USD'}
    assert ReceiptDetails(currency='人民币').currency == 'CNY'
    assert ReceiptDetails(currency='RMB').currency == 'CNY'


def test_cost_summary_preserves_zero_unknown_currency_and_duplicate_status(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            docs = [
                Document(owner_id=user.id, document_type='医疗发票 / 收费单', title='零元票据',
                         primary_date=date(2026, 1, 2), hospital='合成医院'),
                Document(owner_id=user.id, document_type='医疗发票 / 收费单', title='未知金额',
                         primary_date=date(2026, 2, 2), hospital='合成医院'),
                Document(owner_id=user.id, document_type='医疗发票 / 收费单', title='美元票据',
                         primary_date=None, hospital='另一医院'),
                Document(owner_id=user.id, document_type='医疗发票 / 收费单', title='重复票据',
                         primary_date=date(2026, 1, 2), amount=Decimal('999.00'), hospital='合成医院'),
            ]
            db.add_all(docs)
            await db.flush()
            db.add_all([
                ReceiptDetail(owner_id=user.id, document_id=docs[0].id, total_amount=Decimal('0'),
                              insurance_amount=Decimal('0'), personal_amount=Decimal('0'), currency='CNY'),
                ReceiptDetail(owner_id=user.id, document_id=docs[1].id, total_amount=None, currency='CNY'),
                ReceiptDetail(owner_id=user.id, document_id=docs[2].id, total_amount=Decimal('12.34'), currency='USD'),
                ReceiptDetail(owner_id=user.id, document_id=docs[3].id, total_amount=Decimal('999'), currency='CNY',
                              status='duplicate'),
            ])
            await db.commit()
    asyncio.run(seed())

    body = client.get('/api/costs/summary').json()
    cny = next(x for x in body['totals_by_currency'] if x['currency'] == 'CNY')
    usd = next(x for x in body['totals_by_currency'] if x['currency'] == 'USD')
    assert cny == {'currency': 'CNY', 'total': '0.00', 'known_count': 1, 'unknown_count': 1}
    assert usd['total'] == '12.34'
    assert body['excluded_count'] == 1
    assert body['undated']['known_count'] == 1
    cny_payment = next(x for x in body['payments_by_currency'] if x['currency'] == 'CNY')
    assert cny_payment == {'currency': 'CNY', 'insurance_total': '0.00', 'insurance_count': 1,
                           'personal_total': '0.00', 'personal_count': 1}

    unknown = client.get('/api/costs/receipts?unknown_amount=true').json()
    assert [x['title'] for x in unknown['items']] == ['未知金额']
    assert unknown['items'][0]['amount'] is None


def test_cost_receipts_are_paginated_and_owner_scoped(client, app, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            for index in range(103):
                doc = Document(owner_id=user.id, document_type='医疗发票 / 收费单', title=f'合成票据 {index:03}',
                               primary_date=date(2025, 1, 1), hospital='合成医院')
                db.add(doc)
                await db.flush()
                db.add(ReceiptDetail(owner_id=user.id, document_id=doc.id,
                                     total_amount=Decimal(index), currency='CNY'))
            await db.commit()
    asyncio.run(seed())
    first = client.get('/api/costs/receipts?limit=100').json()
    second = client.get(f"/api/costs/receipts?limit=100&cursor={first['next_cursor']}").json()
    assert len(first['items']) == 100
    assert len(second['items']) == 3

    invitation = client.post('/api/admin/invitations', json={'email': 'cost-other@example.test'}).json()
    from fastapi.testclient import TestClient
    with TestClient(app) as other:
        other.post('/api/auth/register/invitation', json={'token': invitation['token'], 'password': 'Correct-Horse-43'})
        assert other.get('/api/costs/summary').json()['receipts']['total'] == 0


def test_user_can_mark_a_receipt_duplicate_with_version_and_reverse_it(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            docs = [Document(owner_id=user.id, document_type='医疗发票 / 收费单', title=f'去重票据 {i}',
                             primary_date=date(2026, 3, 1), hospital='合成医院') for i in range(2)]
            db.add_all(docs); await db.flush()
            receipts = [ReceiptDetail(owner_id=user.id, document_id=doc.id, total_amount=Decimal('10'),
                                      currency='CNY') for doc in docs]
            db.add_all(receipts); await db.commit()
            return str(receipts[0].id), str(receipts[1].id)
    first, duplicate = asyncio.run(seed())
    changed = client.patch(f'/api/costs/receipts/{duplicate}', json={
        'expected_version': 1, 'status': 'duplicate', 'duplicate_of_id': first,
    })
    assert changed.status_code == 200
    assert changed.json()['version'] == 2
    assert client.get('/api/costs/summary').json()['receipts']['total'] == 1
    assert client.get('/api/costs/receipts?include_excluded=true').json()['total'] == 2
    assert client.patch(f'/api/costs/receipts/{duplicate}', json={
        'expected_version': 1, 'status': 'active',
    }).status_code == 409
    restored = client.patch(f'/api/costs/receipts/{duplicate}', json={
        'expected_version': 2, 'status': 'active',
    })
    assert restored.status_code == 200
    assert client.get('/api/costs/summary').json()['receipts']['total'] == 2
