from collections import defaultdict
from uuid import UUID

from sqlalchemy import select

from app.models import Document, LabResult, MetricDefinition, MetricEntry, User
from app.services.metric_catalog import ensure_catalog
from app.services.metric_queries import query_metric_results


def _point(item, axis):
    point = {'x': item[axis], 'y': item['value1']}
    if item.get('value2') is not None:
        point['y2'] = item['value2']
    return point


def _ordinary_series(items):
    grouped = defaultdict(list)
    for item in items:
        if item.get('record_date') and item.get('value1') is not None:
            grouped[item.get('comparison_group') or 'unknown'].append(item)
    result = []
    for key, rows in grouped.items():
        rows.sort(key=lambda item: (item['record_date'], item['id']))
        result.append({'key': key, 'unit': rows[-1].get('unit'),
                       'points': [_point(item, 'record_date') for item in rows]})
    return result


def _ogtt_series(items):
    sessions = defaultdict(list)
    for item in items:
        if item.get('test_session_id') and item.get('timepoint_minutes') is not None:
            sessions[item['test_session_id']].append(item)
    if not sessions:
        return [], [], 0
    latest_id, latest = max(sessions.items(), key=lambda pair: max(
        (item.get('record_date') or '' for item in pair[1]), default=''))
    grouped = defaultdict(list)
    for item in latest:
        if item.get('value1') is not None:
            grouped[item.get('comparison_group') or 'unknown'].append(item)
    series = []
    for key, rows in grouped.items():
        rows.sort(key=lambda item: (item['timepoint_minutes'], item['id']))
        series.append({'key': key, 'unit': rows[-1].get('unit'),
                       'points': [_point(item, 'timepoint_minutes') for item in rows]})
    return series, latest, len(sessions)


def _latest_display(item):
    if not item:
        return None
    return ' '.join(part for part in [item.get('raw_value'), item.get('unit')] if part)


async def build_metric_summaries(db, owner_id):
    await ensure_catalog(db, owner_id)
    metrics = (await db.scalars(select(MetricDefinition).where(
        MetricDefinition.owner_id == owner_id).order_by(
        MetricDefinition.followed.desc(), MetricDefinition.sort_order, MetricDefinition.created_at))).all()
    if not metrics:
        return []
    lab_rows = (await db.execute(select(LabResult, Document).join(
        Document, Document.id == LabResult.document_id).where(
            LabResult.owner_id == owner_id, Document.owner_id == owner_id,
            Document.deleted_at.is_(None)))).all()
    manual_rows = (await db.scalars(select(MetricEntry).where(
        MetricEntry.owner_id == owner_id, MetricEntry.voided_at.is_(None),
        MetricEntry.review_status == 'confirmed'))).all()
    manual_by_metric = defaultdict(list)
    for row in manual_rows:
        manual_by_metric[row.metric_id].append(row)
    summaries = []
    for metric in metrics:
        result = await query_metric_results(db, owner_id, metric, lab_rows=lab_rows,
                                            manual_rows=manual_by_metric[metric.id])
        items = result['items']
        if not items and not metric.followed and not metric.dashboard_visible:
            continue
        latest = items[0] if items else None
        if metric.key.startswith('ogtt_'):
            trend_series, latest_session, record_count = _ogtt_series(items)
            if latest_session:
                latest_session.sort(key=lambda item: (item['timepoint_minutes'], item['id']))
                latest = max(latest_session, key=lambda item: (item.get('record_date') or '', item['id']))
                unit = latest_session[0].get('unit') or ''
                values = ' / '.join(f"{item['timepoint_minutes']}分钟 {item['raw_value']}" for item in latest_session)
                latest_result = f'{values} {unit}'.strip()
            else:
                latest_result = None
            trend_axis = 'minutes'
        else:
            trend_series = _ordinary_series(items)
            record_count = len(items) if metric.record_type != 'group' else len({
                item['record_date'] for item in items if item.get('record_date')})
            latest_result = _latest_display(latest)
            trend_axis = 'dates'
        summaries.append({
            'id': str(metric.id), 'key': metric.key, 'name': metric.name, 'group': metric.group_name,
            'record_type': metric.record_type, 'unit': metric.unit,
            'component_labels': metric.component_labels or [], 'followed': metric.followed,
            'dashboard_visible': metric.dashboard_visible, 'sort_order': metric.sort_order,
            'version': metric.version, 'latest_result': latest_result,
            'latest_date': latest.get('record_date') if latest else None,
            'record_count': record_count, 'trend_axis': trend_axis, 'trend_series': trend_series,
            'manual_entry_allowed': metric.record_type != 'group', 'excluded': result['excluded'],
        })
    return summaries


async def select_dashboard_metrics(db, owner_id, summaries):
    """Persist up to ten initial result-bearing metrics, then honor manual selection."""
    user = await db.scalar(select(User).where(User.id == owner_id).with_for_update())
    selected = {item['id'] for item in summaries if item['dashboard_visible']}
    if not user.dashboard_customized and len(selected) < 10:
        candidates = sorted(
            (item for item in summaries if item['record_count'] > 0 and item['id'] not in selected),
            key=lambda item: (item['latest_date'] or '', -item['sort_order'], item['id']),
            reverse=True,
        )
        additions = candidates[:10 - len(selected)]
        if additions:
            ids = {UUID(item['id']) for item in additions}
            definitions = (await db.scalars(select(MetricDefinition).where(
                MetricDefinition.owner_id == owner_id, MetricDefinition.id.in_(ids)))).all()
            for definition in definitions:
                definition.dashboard_visible = True
            for item in additions:
                item['dashboard_visible'] = True
            await db.commit()
    return sorted(
        (item for item in summaries if item['dashboard_visible']),
        key=lambda item: (item['latest_date'] or '', -item['sort_order'], item['id']),
        reverse=True,
    )
