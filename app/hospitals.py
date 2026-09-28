"""Conservative hospital-name equivalence for verified aliases."""

import re
import unicodedata


_SHANGHAI_PULMONARY_ALIASES = {
    '上海市肺科医院',
    '上海市职业病防治医院',
    '上海市职业病防治院',
}


def hospital_key(name: str | None) -> str:
    """Return a grouping key without changing the extracted hospital text."""
    if not name:
        return ''
    normalized = re.sub(r'\s+', '', unicodedata.normalize('NFKC', name))
    parts = [part for part in re.split(r'[、,，;；/／()（）]+', normalized) if part]
    if parts and all(part in _SHANGHAI_PULMONARY_ALIASES for part in parts):
        return '上海市肺科医院'
    return normalized
