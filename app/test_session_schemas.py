from datetime import date
from uuid import UUID

from pydantic import Field

from app.schemas import StrictModel


class TestSessionCreate(StrictModel):
    name: str = Field(min_length=1, max_length=300)
    session_date: date | None = None
    hospital: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    lab_result_ids: list[UUID] = Field(default_factory=list, max_length=200)
    source_unit_ids: list[UUID] = Field(default_factory=list, max_length=200)


class TestSessionUpdate(TestSessionCreate):
    expected_version: int = Field(ge=1)
