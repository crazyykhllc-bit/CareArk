import hashlib
import re
import unicodedata

from sqlalchemy import select

from app.models import MetricDefinition
from app.services.metric_catalog import ensure_catalog
from app.services.metric_matching import lab_matches_metric


def _canonical(value):
    if not value:
        return ''
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '_', unicodedata.normalize('NFKC', value).casefold()).strip('_')


def _unknown_key(lab):
    analyte = _canonical(lab.analyte_key)
    if analyte:
        return f'lab:{analyte}'[:200]
    name = _canonical(lab.name)
    digest = hashlib.sha256(name.encode('utf-8')).hexdigest()[:24]
    return f'lab:name:{digest}'


def _preset_for_lab(definitions, lab):
    if lab.timepoint_minutes is not None:
        for key in ('ogtt_glucose', 'ogtt_insulin'):
            metric = definitions.get(key)
            if metric and lab_matches_metric(key, lab.analyte_key, lab.name, lab.condition):
                return metric
    for metric in definitions.values():
        if not metric.preset or metric.key.startswith('ogtt_'):
            continue
        if lab_matches_metric(metric.key, lab.analyte_key, lab.name, lab.condition):
            return metric
    return None


async def discover_metrics(db, owner_id, labs):
    """Create owner-local definitions for confirmed report analytes not in the preset catalog."""
    await ensure_catalog(db, owner_id, commit=False)
    rows = (await db.scalars(select(MetricDefinition).where(MetricDefinition.owner_id == owner_id))).all()
    definitions = {row.key: row for row in rows}
    discovered = []
    for lab in labs:
        if lab.owner_id != owner_id or lab.review_status != 'confirmed':
            continue
        metric = _preset_for_lab(definitions, lab)
        key = _unknown_key(lab)
        if metric is None:
            metric = definitions.get(key)
        if metric is None:
            metric = MetricDefinition(
                owner_id=owner_id,
                key=key,
                name=lab.name.strip(),
                group_name='其他检验指标',
                record_type='numeric' if lab.result_type == 'numeric' else 'qualitative',
                unit=lab.unit.strip() if lab.unit else None,
                aliases=[lab.name.strip()],
                component_labels=[],
                followed=False,
                sort_order=1000,
                preset=False,
            )
            db.add(metric)
            await db.flush()
            definitions[key] = metric
        elif not metric.preset and lab.name.strip() not in metric.aliases:
            metric.aliases = [*metric.aliases, lab.name.strip()]
        discovered.append(metric)
    return discovered
