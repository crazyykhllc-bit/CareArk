from __future__ import annotations

from datetime import date as CalendarDate
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas import StrictModel


EventKind = Literal['outpatient', 'inpatient', 'examination', 'laboratory', 'checkup', 'procedure', 'followup', 'other']
DateBasis = Literal['visit', 'admission', 'examination', 'sampling', 'procedure', 'report', 'user_confirmed', 'unknown']


class SourceReference(StrictModel):
    document_id: UUID
    source_unit_id: UUID | None = None
    page: int | None = Field(default=None, ge=1)
    field: str | None = None
    quote: str | None = Field(default=None, max_length=1000)
    document_version: int | None = None


class CareFact(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1000)
    origin: Literal['source', 'user_note'] = 'source'
    category: Literal['historical_reference', 'general'] | None = None
    date: CalendarDate | None = None
    date_basis: DateBasis | None = None
    source_refs: list[SourceReference] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def require_source(self):
        if self.origin == 'source' and not self.source_refs:
            raise ValueError('原文事项必须关联资料来源')
        if self.origin == 'user_note' and self.source_refs:
            raise ValueError('个人备注不能伪装为原文来源')
        return self


class EventCreate(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    hospital: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    event_kind: EventKind = 'other'
    date: CalendarDate | None = None
    date_end: CalendarDate | None = None
    date_basis: DateBasis = 'user_confirmed'
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    user_note: str | None = Field(default=None, max_length=5000)

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError('标题不能为空')
        return value.strip()


class EventUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    hospital: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    event_kind: EventKind | None = None
    date: CalendarDate | None = None
    date_end: CalendarDate | None = None
    date_basis: DateBasis | None = None
    summary_facts: list[CareFact] | None = Field(default=None, max_length=20)
    milestones: list[CareFact] | None = Field(default=None, max_length=30)
    user_note: str | None = Field(default=None, max_length=5000)


class TopicCreate(StrictModel):
    name: str = Field(min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=5000)
    event_ids: list[UUID] = Field(default_factory=list, max_length=100)
    document_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError('主题名称不能为空')
        return value.strip()


class TopicUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=5000)
    status: Literal['active', 'archived'] | None = None


class VersionAction(StrictModel):
    expected_version: int = Field(ge=1)


class SuggestionAccept(VersionAction):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    date: CalendarDate | None = None
    date_basis: DateBasis | None = None

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, value):
        if value is not None and not value.strip():
            raise ValueError('标题不能为空')
        return value.strip() if value is not None else None
