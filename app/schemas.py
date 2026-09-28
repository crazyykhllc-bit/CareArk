from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(StrictModel):
    page: int | None = Field(default=None, ge=1)
    quote: str | None = None


class DocumentDraft(StrictModel):
    type: Literal[
        "挂号单 / 就诊单",
        "门诊病历",
        "检验报告",
        "检查报告",
        "处方 / 用药单",
        "医疗发票 / 收费单",
        "其他医疗资料",
    ]
    title: str
    primary_date: date | None = None
    primary_date_raw: str | None = None
    hospital: str | None = None
    department: str | None = None
    doctor: str | None = None
    amount: str | None = None
    key_information: list[str] = Field(default_factory=list)
    parsed_content: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    patient_scope: Literal['self', 'other', 'unconfirmed'] = 'unconfirmed'
    details: 'DocumentDetails' = Field(default_factory=lambda: DocumentDetails())


class LabResultDraft(StrictModel):
    name: str
    result: str | None = None
    unit: str | None = None
    reference_range: str | None = None
    flag: str | None = None
    source_ref: SourceRef | None = None
    analyte_key: str | None = None
    specimen: str | None = None
    condition: str | None = None
    observed_date: date | None = None
    timepoint_minutes: int | None = Field(default=None, ge=0, le=1440)
    test_session_key: str | None = None
    source_id: str | None = None
    result_type: Literal['numeric', 'scientific', 'comparator', 'ratio', 'qualitative', 'unknown'] = 'unknown'
    review_status: Literal['confirmed', 'pending'] = 'pending'


class MedicationDraft(StrictModel):
    drug_key: str
    name: str
    generic_name: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    expiry_date: date | None = None
    quantity: str | None = None
    route: str | None = None
    instructions: str | None = None
    purpose_text: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)


class ExtractionDraft(StrictModel):
    document: DocumentDraft
    lab_results: list[LabResultDraft] = Field(default_factory=list)
    medications: list[MedicationDraft] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)


class MedicationEventInput(StrictModel):
    event_type: Literal["start", "pause", "stop"]
    event_date: date
    expected_version: int = Field(ge=1)
    dose_each_time: str | None = None
    frequency: str | None = None
    timing: str | None = None
    planned_end_date: date | None = None
    note: str | None = None
    package_id: UUID | None = None


from app.document_schemas import DocumentDetails

DocumentDraft.model_rebuild()
