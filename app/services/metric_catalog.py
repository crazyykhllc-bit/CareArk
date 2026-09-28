from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import MetricDefinition


PRESETS = [
    ('fasting_glucose', '空腹血糖', '血糖', 'numeric', 'mmol/L', ['空腹血糖', 'FPG', 'GLU'], True, []),
    ('blood_pressure', '血压', '血压', 'pair', 'mmHg', ['血压', '收缩压/舒张压'], True, ['收缩压', '舒张压']),
    ('blood_lipids', '血脂', '血脂', 'group', 'mmol/L', ['总胆固醇', '甘油三酯', 'HDL-C', 'LDL-C'], True, []),
    ('serum_uric_acid', '血尿酸', '尿酸', 'numeric', 'μmol/L', ['血尿酸', '尿酸'], True, []),
    ('weight', '体重', '体重', 'numeric', 'kg', ['体重'], True, []),
    ('serum_creatinine', '血肌酐', '肾功能', 'numeric', 'μmol/L', ['血肌酐', '肌酐'], False, []),
    ('tsh', '促甲状腺激素', '甲状腺', 'numeric', 'mIU/L', ['促甲状腺激素', 'TSH'], False, []),
    ('ogtt_glucose', 'OGTT 血糖', '血糖', 'group', 'mmol/L', ['OGTT血糖'], False, []),
    ('ogtt_insulin', 'OGTT 胰岛素', '胰岛素', 'group', 'μIU/mL', ['OGTT胰岛素'], False, []),
]


async def ensure_catalog(db, owner_id, *, commit=True):
    existing = {x for x in (await db.scalars(select(MetricDefinition.key).where(MetricDefinition.owner_id == owner_id))).all()}
    for order, (key, name, group, kind, unit, aliases, followed, labels) in enumerate(PRESETS, 1):
        if key not in existing:
            db.add(MetricDefinition(owner_id=owner_id, key=key, name=name, group_name=group,
                record_type=kind, unit=unit, aliases=aliases, followed=followed,
                component_labels=labels, sort_order=order * 10, preset=True))
    try:
        if commit:
            await db.commit()
        else:
            await db.flush()
    except IntegrityError:
        # Two first-page requests can initialize the same user's catalog concurrently.
        await db.rollback()
