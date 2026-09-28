import re
import unicodedata


def comparison_group(unit: str | None) -> str:
    """Group spelling-equivalent units only; no clinical conversion is inferred."""
    if not unit or not unit.strip():
        return 'unit:unknown'
    value = unicodedata.normalize('NFKC', unit).strip().replace('μ', 'u').replace('µ', 'u')
    value = re.sub(r'\s+', '', value).casefold()
    return f'unit:{value}'
