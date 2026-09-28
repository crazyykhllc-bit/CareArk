from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas import StrictModel


MetricType = Literal['numeric', 'pair', 'qualitative', 'group']


class MetricCreate(StrictModel):
    name: str = Field(min_length=1, max_length=300)
    group: str = Field(min_length=1, max_length=100)
    record_type: MetricType
    unit: str | None = Field(default=None, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    followed: bool = True
    component_labels: list[str] = Field(default_factory=list, max_length=10)

    @field_validator('name', 'group')
    @classmethod
    def meaningful_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('名称不能为空')
        return value

    @model_validator(mode='after')
    def supported_shape(self):
        if self.record_type == 'group':
            raise ValueError('自定义指标暂不支持复杂指标组')
        if self.record_type == 'pair' and (len(self.component_labels) != 2 or
                                           any(not value.strip() for value in self.component_labels)):
            raise ValueError('双数值指标需要两个分量名称')
        return self


class MetricUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    followed: bool | None = None
    dashboard_visible: bool | None = None
    sort_order: int | None = None


class MetricEntryCreate(StrictModel):
    metric_id: UUID
    record_date: date
    raw_value: str = Field(min_length=1, max_length=500)
    value1: Decimal | None = None
    value2: Decimal | None = None
    text_value: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=100)
    condition: str | None = Field(default=None, max_length=200)
    review_status: Literal['confirmed', 'pending'] = 'confirmed'
    note: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=100)

    @field_validator('value1', 'value2')
    @classmethod
    def finite_number(cls, value):
        if value is not None and not value.is_finite():
            raise ValueError('数值必须有限')
        return value


class MetricEntryUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    record_date: date | None = None
    raw_value: str | None = Field(default=None, min_length=1, max_length=500)
    value1: Decimal | None = None
    value2: Decimal | None = None
    text_value: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=100)
    condition: str | None = Field(default=None, max_length=200)
    review_status: Literal['confirmed', 'pending'] | None = None
    note: str | None = None
    voided: bool | None = None

    @field_validator('value1', 'value2')
    @classmethod
    def finite_number(cls, value):
        if value is not None and not value.is_finite():
            raise ValueError('数值必须有限')
        return value
