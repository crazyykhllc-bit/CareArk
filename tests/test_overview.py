import asyncio
from datetime import date
from uuid import UUID

from app.models import Document, User
from tests.test_uploads import setup_admin


def test_overview_aggregates_complete_dataset_beyond_list_page(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            user = await db.get(User, UUID(owner['id']))
            for index in range(105):
                db.add(Document(owner_id=user.id, document_type='检验报告' if index % 2 else '检查报告',
                                title=f'合成资料 {index}', primary_date=date(2026, 9, 1 + index % 10),
                                hospital=f'合成医院 {index % 3}'))
            db.add(Document(owner_id=user.id, document_type='其他医疗资料', title='日期待确认',
                            primary_date_raw='2026-02-30', hospital=None))
            await db.commit()
    asyncio.run(seed())

    response = client.get('/api/overview')
    assert response.status_code == 200
    body = response.json()
    assert body['documents']['total'] == 106
    assert body['documents']['dated'] == 105
    assert body['documents']['undated'] == 1
    assert body['hospitals'] == 3
    assert body['latest_date'] == '2026-09-10'
    assert sum(x['count'] for x in body['types']) == 106


def test_overview_counts_outpatient_records_as_their_own_type(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            db.add(Document(owner_id=UUID(owner['id']), document_type='门诊病历',
                            title='合成门诊记录'))
            await db.commit()

    asyncio.run(seed())
    response = client.get('/api/overview')

    assert response.status_code == 200
    assert {'type': '门诊病历', 'count': 1} in response.json()['types']
