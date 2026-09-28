from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, LabResult, MetricDefinition, MetricEntry
from app.services.metric_matching import analyte_matches, lab_matches_metric, metric_matches_lab, matched_series, parse_strict_number, parse_strict_pair
from app.services.metric_normalization import comparison_group


def _claimed_by_preset(lab: LabResult) -> bool:
    if lab.timepoint_minutes is not None and any(
        lab_matches_metric(key, lab.analyte_key, lab.name, lab.condition)
        for key in ('ogtt_glucose', 'ogtt_insulin')
    ):
        return True
    return any(
        lab_matches_metric(key, lab.analyte_key, lab.name, lab.condition)
        for key in ('fasting_glucose', 'blood_pressure', 'blood_lipids',
                    'serum_uric_acid', 'weight', 'serum_creatinine', 'tsh')
    )


async def query_metric_results(db: AsyncSession, owner_id, metric: MetricDefinition, *,
                               lab_rows=None, manual_rows=None, include_manual=True) -> dict:
    items = []
    excluded = Counter()
    if not include_manual:
        manual = []
    elif manual_rows is not None:
        manual = manual_rows
    else:
        manual = (await db.scalars(select(MetricEntry).where(
            MetricEntry.owner_id == owner_id, MetricEntry.metric_id == metric.id,
            MetricEntry.voided_at.is_(None), MetricEntry.review_status == 'confirmed'
        ))).all()
    for row in manual:
        items.append({
            'id': str(row.id), 'source_type': 'manual', 'source_id': str(row.id),
            'version': row.version,
            'record_date': row.record_date.isoformat(), 'raw_value': row.raw_value,
            'value1': str(row.value1) if row.value1 is not None else None,
            'value2': str(row.value2) if row.value2 is not None else None,
            'text_value': row.text_value, 'unit': row.unit,
            'comparison_group': comparison_group(row.unit), 'condition': row.condition,
        })

    if lab_rows is None:
        lab_rows = (await db.execute(select(LabResult, Document).join(Document, Document.id == LabResult.document_id)
            .where(LabResult.owner_id == owner_id, Document.owner_id == owner_id,
                   Document.deleted_at.is_(None)))).all()
    for lab, document in lab_rows:
        if metric.preset and not analyte_matches(metric.key, lab.analyte_key, lab.name):
            continue
        if not metric.preset and not metric_matches_lab(metric, lab.analyte_key, lab.name, lab.condition):
            continue
        if metric.key.startswith('lab:') and _claimed_by_preset(lab):
            continue
        if document.patient_scope != 'self':
            excluded['patient_scope'] += 1
            continue
        if metric.key in {'ogtt_glucose', 'ogtt_insulin'} and lab.test_session_id is None:
            excluded['session_required'] += 1
            continue
        if lab.review_status != 'confirmed':
            excluded['pending_review'] += 1
            continue
        if metric.preset and not lab_matches_metric(metric.key, lab.analyte_key, lab.name, lab.condition):
            excluded['condition_mismatch'] += 1
            continue
        qualitative = metric.record_type == 'qualitative'
        pair = parse_strict_pair(lab.result) if metric.record_type == 'pair' else None
        value = None if qualitative else (pair[0] if pair else parse_strict_number(lab.result))
        if qualitative and not (lab.result or '').strip():
            excluded['empty_result'] += 1
            continue
        if not qualitative and value is None:
            excluded['non_numeric'] += 1
            continue
        record_date = lab.observed_date or document.primary_date
        series_key = matched_series(metric.key, lab.analyte_key, lab.name) if metric.preset else metric.key
        unit_group = comparison_group(lab.unit)
        if metric.record_type == 'group':
            unit_group = f'series:{series_key}|{unit_group}'
        items.append({
            'id': str(lab.id), 'source_type': 'lab_report', 'source_id': str(document.id),
            'source_unit_id': str(lab.source_unit_id) if lab.source_unit_id else None,
            'record_date': record_date.isoformat() if record_date else None,
            'raw_value': lab.result, 'value1': str(value) if value is not None else None,
            'value2': str(pair[1]) if pair else None,
            'text_value': lab.result.strip() if qualitative else None, 'unit': lab.unit,
            'comparison_group': unit_group, 'series_key': series_key, 'condition': lab.condition,
            'reference_range': lab.reference_range, 'flag': lab.flag,
            'test_session_id': str(lab.test_session_id) if lab.test_session_id else None,
            'timepoint_minutes': lab.timepoint_minutes,
        })
    items.sort(key=lambda x: (x['record_date'] is not None, x['record_date'] or '', x['id']), reverse=True)
    return {'items': items, 'excluded': dict(excluded)}
