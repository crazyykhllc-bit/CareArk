import re
from decimal import Decimal, InvalidOperation


_YUAN_AMOUNT = re.compile(
    r'^\s*(?:(?:人民币|RMB|CNY)\s*)?[¥￥]?\s*([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:元)?\s*$',
    re.IGNORECASE,
)


def parse_amount(value: str | Decimal) -> Decimal:
    """Read an exact amount, accepting a yuan label without storing it in the number."""
    if isinstance(value, str):
        match = _YUAN_AMOUNT.fullmatch(value)
        if not match:
            raise ValueError('金额格式不正确')
        value = match.group(1).replace(',', '')
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError) as error:
        raise ValueError('金额格式不正确') from error
    if not amount.is_finite():
        raise ValueError('金额必须是有限十进制数')
    return amount


def canonical_currency(value: str) -> str:
    """Normalize common currency labels without converting between currencies."""
    currency = value.strip()
    if currency.upper() in {'CNY', 'RMB'} or currency in {'人民币', '人民币元', '元', '¥', '￥'}:
        return 'CNY'
    if currency.upper() == 'USD' or currency in {'美元', '美金'}:
        return 'USD'
    return currency.upper() if currency.isascii() else currency
