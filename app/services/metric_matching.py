import re
import unicodedata
from decimal import Decimal, InvalidOperation


_NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')

ANALYTE_KEYS = {
    'fasting_glucose': {'glucose', 'fasting_glucose', 'fpg', 'glu'},
    'blood_pressure': {'blood_pressure', 'bp'},
    'triglycerides': {'triglycerides', 'triglyceride', 'tg'},
    'serum_uric_acid': {'uric_acid', 'serum_uric_acid', 'ua'},
    'serum_creatinine': {'creatinine', 'serum_creatinine', 'scr', 'crea'},
    'tsh': {'tsh', 'thyroid_stimulating_hormone'},
    'weight': {'weight'},
}

EXACT_NAMES = {
    'fasting_glucose': {'空腹血糖', '葡萄糖', '血糖', 'glu', 'fpg'},
    'blood_pressure': {'血压', '收缩压 / 舒张压', '收缩压/舒张压', 'bp'},
    'triglycerides': {'甘油三酯', '甘油三脂', 'triglycerides', 'tg'},
    'serum_uric_acid': {'血尿酸', '尿酸', 'uric acid', 'ua'},
    'serum_creatinine': {'血肌酐', '肌酐', 'creatinine', 'scr'},
    'tsh': {'促甲状腺激素', '促甲状腺素', 'tsh'},
    'weight': {'体重', 'weight'},
}

GROUP_SERIES = {
    'blood_lipids': {
        'total_cholesterol': ({'total_cholesterol', 'tc'}, {'总胆固醇', 'TC'}),
        'triglycerides': ({'triglycerides', 'triglyceride', 'tg'}, {'甘油三酯', '甘油三脂', 'TG'}),
        'hdl_c': ({'hdl_c', 'hdl'}, {'高密度脂蛋白胆固醇', 'HDL-C', 'HDL'}),
        'ldl_c': ({'ldl_c', 'ldl'}, {'低密度脂蛋白胆固醇', 'LDL-C', 'LDL'}),
    },
    'ogtt_glucose': {
        'glucose': ({'glucose', 'ogtt_glucose', 'glu'}, {'葡萄糖', '血糖', 'GLU'}),
    },
    'ogtt_insulin': {
        'insulin': ({'insulin', 'ogtt_insulin', 'ins'}, {'胰岛素', 'INS'}),
    },
}


def _canonical(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'[\s_\-（）()]+', '', unicodedata.normalize('NFKC', value).casefold())


def parse_strict_number(value: str | None) -> Decimal | None:
    """Parse a complete finite numeric result without guessing qualifiers or ratios."""
    if value is None:
        return None
    text = value.strip()
    if not _NUMBER.fullmatch(text):
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def parse_strict_pair(value: str | None) -> tuple[Decimal, Decimal] | None:
    if value is None:
        return None
    parts = re.split(r'[/／]', value.strip())
    if len(parts) != 2:
        return None
    values = tuple(parse_strict_number(part) for part in parts)
    return values if all(item is not None for item in values) else None


def has_fasting_condition(condition: str | None) -> bool:
    value = _canonical(condition)
    return value in {'空腹', '空腹状态', 'fasting', 'fasted'} or value.startswith('空腹')


def matched_series(metric_key: str, analyte_key: str | None, name: str | None) -> str | None:
    key = _canonical(analyte_key)
    canonical_name = _canonical(name)
    for series, (keys, names) in GROUP_SERIES.get(metric_key, {}).items():
        if (key and key in {_canonical(x) for x in keys}) or (not key and canonical_name in {_canonical(x) for x in names}):
            return series
    if metric_key in GROUP_SERIES:
        return None
    if key:
        return metric_key if key in {_canonical(x) for x in ANALYTE_KEYS.get(metric_key, {metric_key})} else None
    return metric_key if canonical_name in {_canonical(x) for x in EXACT_NAMES.get(metric_key, set())} else None


def analyte_matches(metric_key: str, analyte_key: str | None, name: str | None) -> bool:
    return matched_series(metric_key, analyte_key, name) is not None


def lab_matches_metric(metric_key: str, analyte_key: str | None, name: str | None,
                       condition: str | None) -> bool:
    if not analyte_matches(metric_key, analyte_key, name):
        return False
    if metric_key == 'fasting_glucose':
        return has_fasting_condition(condition)
    return True


def metric_matches_lab(metric, analyte_key: str | None, name: str | None, condition: str | None) -> bool:
    if metric.preset:
        return lab_matches_metric(metric.key, analyte_key, name, condition)
    canonical_key = _canonical(analyte_key)
    stored_key = metric.key[4:] if metric.key.startswith('lab:') and not metric.key.startswith('lab:name:') else ''
    if stored_key and canonical_key == _canonical(stored_key):
        return True
    candidate_name = _canonical(name)
    return bool(candidate_name and candidate_name in {_canonical(alias) for alias in (metric.aliases or [])})
