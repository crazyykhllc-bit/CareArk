from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.currency import canonical_currency, parse_amount


class StrictDocumentModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ExamDetails(StrictDocumentModel):
    exam_name: str | None = None
    clinical_info: str | None = None
    exam_method: str | None = None
    findings: list[str] = Field(default_factory=list)
    impression: list[str] = Field(default_factory=list)


class ReceiptLineItem(StrictDocumentModel):
    name: str = Field(min_length=1, max_length=500)
    unit_price: Decimal | None = None
    quantity: Decimal | None = None
    amount: Decimal | None = None
    insurance_category: str | None = None

    @field_validator('unit_price', 'amount', mode='before')
    @classmethod
    def normalize_money(cls, value):
        if isinstance(value, str):
            return None if not value.strip() else parse_amount(value)
        return value

    @field_validator('quantity', mode='before')
    @classmethod
    def blank_quantity_is_unknown(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class ReceiptDetails(StrictDocumentModel):
    receipt_number: str | None = None
    total_amount: Decimal | None = None
    insurance_amount: Decimal | None = None
    personal_amount: Decimal | None = None
    currency: str = Field(default='CNY', min_length=3, max_length=3)
    settlement_time: str | None = None
    payment_method: str | None = None
    line_items: list[ReceiptLineItem] = Field(default_factory=list)

    @field_validator('currency', mode='before')
    @classmethod
    def normalize_currency(cls, value):
        return canonical_currency(value) if isinstance(value, str) else value

    @field_validator('total_amount', 'insurance_amount', 'personal_amount', mode='before')
    @classmethod
    def blank_is_unknown(cls, value):
        if isinstance(value, str):
            return None if not value.strip() else parse_amount(value)
        return value

    @field_validator('total_amount', 'insurance_amount', 'personal_amount')
    @classmethod
    def finite_amount(cls, value):
        if value is not None and not value.is_finite():
            raise ValueError('金额必须是有限十进制数')
        return value


class DocumentDetails(StrictDocumentModel):
    exam: ExamDetails | None = None
    receipt: ReceiptDetails | None = None
    registration: dict | None = None
    prescription: dict | None = None
    other: dict | None = None
