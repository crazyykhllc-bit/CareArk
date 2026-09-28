import asyncio
from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.models import Document, LabResult, TestSession as SessionModel
from app.services.test_session_grouping import candidate_metadata, group_confirmed_test_results
from tests.test_uploads import setup_admin


async def _seed_document(db, owner_id, title, points, hospital='示例医院', session_key=None):
    document = Document(owner_id=owner_id, document_type='检验报告', title=title,
                        primary_date=date(2026, 7, 10), hospital=hospital, patient_scope='self')
    db.add(document)
    await db.flush()
    labs = []
    for minute, value in points:
        lab = LabResult(owner_id=owner_id, document_id=document.id, name='葡萄糖',
                        analyte_key='glucose', result=value, unit='mmol/L',
                        observed_date=date(2026, 7, 10), timepoint_minutes=minute,
                        test_session_key=session_key, result_type='numeric', review_status='confirmed')
        db.add(lab)
        labs.append(lab)
    await db.flush()
    return document, labs


def test_complete_dynamic_test_document_groups_automatically(client, session_factory):
    owner = setup_admin(client)

    async def run():
        async with session_factory() as db:
            document, labs = await _seed_document(db, UUID(owner['id']), 'OGTT 五点报告',
                                                   [(0, '4.9'), (30, '9.5'), (60, '6.4'), (120, '5.2')])
            decisions = await group_confirmed_test_results(db, document.owner_id, [document.id])
            await db.commit()
            sessions = (await db.scalars(select(SessionModel).where(
                SessionModel.owner_id == document.owner_id))).all()
            return decisions, sessions, [lab.test_session_id for lab in labs]

    decisions, sessions, linked = asyncio.run(run())
    assert decisions[0]['status'] == 'automatic'
    assert len(sessions) == 1
    assert set(linked) == {sessions[0].id}


def test_complementary_ogtt_documents_group_but_same_day_alone_only_suggests(client, session_factory):
    owner = setup_admin(client)

    async def run():
        async with session_factory() as db:
            first, _ = await _seed_document(db, UUID(owner['id']), '口服葡萄糖耐量试验', [(0, '5.0')])
            second, _ = await _seed_document(db, UUID(owner['id']), 'OGTT 检验单', [(120, '7.1')])
            automatic = await group_confirmed_test_results(db, first.owner_id, [first.id, second.id])
            other_a, labs_a = await _seed_document(db, first.owner_id, '上午检验', [(30, '8.0')], hospital='另一医院')
            other_b, labs_b = await _seed_document(db, first.owner_id, '下午检验', [(60, '7.0')], hospital='另一医院')
            suggested = await group_confirmed_test_results(db, first.owner_id, [other_a.id, other_b.id])
            await db.commit()
            return automatic, suggested, labs_a + labs_b

    automatic, suggested, unlinked = asyncio.run(run())
    assert any(item['status'] == 'automatic' for item in automatic)
    assert any(item['status'] == 'suggested' for item in suggested)
    assert all(lab.test_session_id is None for lab in unlinked)


def test_conflicting_duplicate_timepoint_is_never_merged(client, session_factory):
    owner = setup_admin(client)

    async def run():
        async with session_factory() as db:
            first, labs_a = await _seed_document(db, UUID(owner['id']), 'OGTT 报告 A', [(0, '5.0')], session_key='visit-1')
            second, labs_b = await _seed_document(db, UUID(owner['id']), 'OGTT 报告 B', [(0, '6.8')], session_key='visit-1')
            decisions = await group_confirmed_test_results(db, first.owner_id, [first.id, second.id])
            await db.commit()
            return decisions, labs_a + labs_b

    decisions, labs = asyncio.run(run())
    assert decisions[0]['status'] == 'separate'
    assert decisions[0]['reason'] == 'conflicting_duplicate_timepoint'
    assert all(lab.test_session_id is None for lab in labs)


def test_known_hospital_aliases_share_context_without_automatic_merging(client, session_factory):
    owner = setup_admin(client)

    async def run():
        async with session_factory() as db:
            first, _ = await _seed_document(db, UUID(owner['id']), '上午检验', [(30, '8.0')],
                                            hospital='上海市肺科医院')
            second, _ = await _seed_document(db, UUID(owner['id']), '下午检验', [(60, '7.0')],
                                             hospital='上海市职业病防治院')
            decisions = await group_confirmed_test_results(db, first.owner_id, [first.id, second.id])
            await db.commit()
            return decisions

    decisions = asyncio.run(run())
    assert len(decisions) == 1
    assert decisions[0]['status'] == 'suggested'


def test_grouping_candidates_only_include_confirmed_self_documents(client, session_factory):
    owner = setup_admin(client)

    async def run():
        async with session_factory() as db:
            other, _ = await _seed_document(db, UUID(owner['id']), 'OGTT 他人资料', [(0, '5.0')])
            other.patient_scope = 'other'
            pending, labs = await _seed_document(db, UUID(owner['id']), 'OGTT 未确认结果', [(30, '8.0')])
            labs[0].review_status = 'pending'
            await db.commit()
            return await candidate_metadata(db, UUID(owner['id']))

    assert asyncio.run(run()) == {}
