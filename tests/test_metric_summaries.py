import asyncio
from datetime import date
from uuid import UUID

from app.models import Document, LabResult, MetricDefinition, TestSession as SessionModel
from app.services.metric_discovery import discover_metrics
from tests.test_uploads import setup_admin


def test_overview_returns_discovered_metric_with_direct_dated_trend(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            labs = []
            for day, value in [(1, '0.91'), (8, '0.95')]:
                doc = Document(owner_id=UUID(owner['id']), document_type='检验报告', title='肾功能',
                               primary_date=date(2026, 7, day), patient_scope='self')
                db.add(doc)
                await db.flush()
                lab = LabResult(owner_id=doc.owner_id, document_id=doc.id, name='胱抑素 C',
                                analyte_key='cystatin_c', result=value, unit='mg/L',
                                observed_date=date(2026, 7, day), result_type='numeric',
                                review_status='confirmed')
                db.add(lab)
                labs.append(lab)
            await db.flush()
            await discover_metrics(db, UUID(owner['id']), labs)
            await db.commit()

    asyncio.run(seed())
    response = client.get('/api/overview')

    assert response.status_code == 200
    metric = next(item for item in response.json()['metrics'] if item['key'] == 'lab:cystatin_c')
    assert metric['latest_result'] == '0.95 mg/L'
    assert metric['latest_date'] == '2026-07-08'
    assert metric['record_count'] == 2
    assert metric['trend_series'][0]['points'] == [
        {'x': '2026-07-01', 'y': '0.91'}, {'x': '2026-07-08', 'y': '0.95'},
    ]


def test_overview_does_not_join_different_units_or_invent_second_point(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            labs = []
            for unit, value in [('mg/L', '1.0'), ('μmol/L', '88')]:
                doc = Document(owner_id=UUID(owner['id']), document_type='检验报告', title='项目 Y',
                               primary_date=date(2026, 7, 1), patient_scope='self')
                db.add(doc)
                await db.flush()
                lab = LabResult(owner_id=doc.owner_id, document_id=doc.id, name='项目 Y',
                                analyte_key='item_y', result=value, unit=unit,
                                observed_date=date(2026, 7, 1), result_type='numeric',
                                review_status='confirmed')
                db.add(lab)
                labs.append(lab)
            await db.flush()
            await discover_metrics(db, UUID(owner['id']), labs)
            await db.commit()

    asyncio.run(seed())
    metric = next(item for item in client.get('/api/overview').json()['metrics'] if item['key'] == 'lab:item_y')
    assert len(metric['trend_series']) == 2
    assert all(len(series['points']) == 1 for series in metric['trend_series'])


def test_ogtt_is_an_equal_metric_row_with_latest_session_minute_curve(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            doc = Document(owner_id=UUID(owner['id']), document_type='检验报告', title='OGTT',
                           primary_date=date(2026, 7, 10), hospital='示例医院', patient_scope='self')
            session = SessionModel(owner_id=doc.owner_id, name='OGTT · 2026-07-10',
                                   session_date=date(2026, 7, 10), hospital='示例医院')
            db.add_all([doc, session])
            await db.flush()
            labs = []
            for minute, value in [(0, '4.98'), (30, '9.54'), (120, '5.27')]:
                lab = LabResult(owner_id=doc.owner_id, document_id=doc.id, name='葡萄糖',
                                analyte_key='glucose', result=value, unit='mmol/L',
                                observed_date=date(2026, 7, 10), timepoint_minutes=minute,
                                test_session_id=session.id, result_type='numeric', review_status='confirmed')
                db.add(lab)
                labs.append(lab)
            await db.flush()
            await discover_metrics(db, doc.owner_id, labs)
            await db.commit()

    asyncio.run(seed())
    metric = next(item for item in client.get('/api/overview').json()['metrics'] if item['key'] == 'ogtt_glucose')
    assert metric['name'] == 'OGTT 血糖'
    assert metric['record_count'] == 1
    assert metric['trend_axis'] == 'minutes'
    assert metric['trend_series'][0]['points'] == [
        {'x': 0, 'y': '4.98'}, {'x': 30, 'y': '9.54'}, {'x': 120, 'y': '5.27'},
    ]


def test_blood_pressure_report_pairs_produce_two_chart_lines(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            for day, value in [(1, '114 / 72'), (10, '113 / 71')]:
                doc = Document(owner_id=UUID(owner['id']), document_type='检验报告',
                               title='血压报告', primary_date=date(2026, 7, day), patient_scope='self')
                db.add(doc)
                await db.flush()
                db.add(LabResult(owner_id=doc.owner_id, document_id=doc.id,
                                 name='收缩压 / 舒张压', analyte_key='BP', result=value,
                                 unit='mmHg', observed_date=date(2026, 7, day),
                                 result_type='numeric', review_status='confirmed'))
            await db.commit()

    asyncio.run(seed())
    metric = next(item for item in client.get('/api/overview').json()['metrics'] if item['key'] == 'blood_pressure')
    assert metric['record_count'] == 2
    assert metric['component_labels'] == ['收缩压', '舒张压']
    assert metric['trend_series'][0]['points'] == [
        {'x': '2026-07-01', 'y': '114', 'y2': '72'},
        {'x': '2026-07-10', 'y': '113', 'y2': '71'},
    ]


def test_legacy_discovered_glu_does_not_duplicate_preset_fasting_results(client, session_factory):
    owner = setup_admin(client)

    async def seed():
        async with session_factory() as db:
            owner_id = UUID(owner['id'])
            db.add(MetricDefinition(owner_id=owner_id, key='lab:glu', name='葡萄糖',
                                    group_name='其他检验指标', record_type='numeric',
                                    unit='mmol/L', aliases=['葡萄糖'], component_labels=[],
                                    followed=False, preset=False))
            for day in (1, 10):
                doc = Document(owner_id=owner_id, document_type='检验报告', title='血糖报告',
                               primary_date=date(2026, 7, day), patient_scope='self')
                db.add(doc)
                await db.flush()
                db.add(LabResult(owner_id=owner_id, document_id=doc.id, name='葡萄糖',
                                 analyte_key='GLU', result='4.9', unit='mmol/L',
                                 condition='空腹', observed_date=date(2026, 7, day),
                                 result_type='numeric', review_status='confirmed'))
            await db.commit()

    asyncio.run(seed())
    metrics = client.get('/api/overview').json()['metrics']
    assert next(item for item in metrics if item['key'] == 'fasting_glucose')['record_count'] == 2
    assert not any(item['key'] == 'lab:glu' for item in metrics)
