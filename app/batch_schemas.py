from datetime import date as CalendarDate
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas import StrictModel, DocumentDraft, LabResultDraft


class CareTarget(StrictModel):
    mode: Literal['small', 'new_topic', 'existing_topic', 'existing_event', 'archive'] = 'small'
    name: str | None = Field(default=None, max_length=300)
    topic_id: UUID | None = None
    event_id: UUID | None = None

    @model_validator(mode='after')
    def valid_target(self):
        if self.mode == 'existing_topic' and not self.topic_id:
            raise ValueError('请选择已有大事件')
        if self.mode == 'existing_event' and not self.event_id:
            raise ValueError('请选择已有小事件')
        if self.mode not in ('existing_topic', 'new_topic') and self.topic_id:
            raise ValueError('归属模式与大事件目标不一致')
        if self.mode != 'existing_event' and self.event_id:
            raise ValueError('归属模式与小事件目标不一致')
        return self


class UploadCareIntent(CareTarget):
    intent_key: str = Field(min_length=1, max_length=100)


class CreateBatch(StrictModel):
    care_context: UploadCareIntent | None = None


class FileGroup(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal['document', 'medication']
    label: str = Field(default='', max_length=300)
    file_ids: list[str] = Field(min_length=1, max_length=20)


class VisitHint(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(default='', max_length=300)
    file_ids: list[str] = Field(min_length=1, max_length=20)


class BatchSubmit(StrictModel):
    expected_version: int
    groups: list[FileGroup] = Field(default_factory=list, max_length=20)
    encounters: list[VisitHint] = Field(default_factory=list, max_length=20)


class Evidence(StrictModel):
    source_id: str
    field: str
    quote: str


class PackageDraft(StrictModel):
    batch_number: str | None = None
    expiry_date: CalendarDate | None = None
    quantity_raw: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class BatchMedication(StrictModel):
    name: str = Field(min_length=1, max_length=300)
    generic_name: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    manufacturer: str | None = None
    approval_number: str | None = None
    route: str | None = None
    instructions: str | None = None
    purpose_text: str | None = None
    existing_medication_id: UUID | None = None
    packages: list[PackageDraft] = Field(default_factory=list)


class ResultGroup(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal['document', 'medication']
    source_ids: list[str] = Field(min_length=1, max_length=100)
    encounter_id: str | None = None
    patient_identity: str | None = None
    document: DocumentDraft
    lab_results: list[LabResultDraft] = Field(default_factory=list)
    medications: list[BatchMedication] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)


class VisitDraft(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    hospital: str | None = None
    date: CalendarDate | None = None
    date_end: CalendarDate | None = None
    date_basis: Literal['visit', 'admission', 'examination', 'sampling', 'procedure', 'report', 'user_confirmed', 'unknown'] = 'unknown'
    event_kind: Literal['outpatient', 'inpatient', 'examination', 'laboratory', 'checkup', 'procedure', 'followup', 'other'] = 'other'
    department: str | None = None
    historical_mentions: list[str] = Field(default_factory=list, max_length=20)
    patient_identity: str | None = None
    evidence: list[str] = Field(default_factory=list)
    existing_encounter_id: UUID | None = None


class ExcludedSource(StrictModel):
    source_id: str
    reason: str = Field(min_length=1, max_length=500)


class PlannedResultGroup(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal['document', 'medication']
    source_ids: list[str] = Field(min_length=1, max_length=100)
    encounter_id: str | None = None


class BatchMergePlan(StrictModel):
    groups: list[PlannedResultGroup] = Field(default_factory=list, max_length=100)
    encounters: list[VisitDraft] = Field(default_factory=list, max_length=100)
    excluded_sources: list[ExcludedSource] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)


class GroupDetailDocument(DocumentDraft):
    # Raw transcription is attached by the server instead of generated again.
    parsed_content: None = None


class GroupDetailExtraction(ResultGroup):
    document: GroupDetailDocument


class SourceTranscription(StrictModel):
    source_id: str
    content: str
    visual_notes: list[str] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)


class SourceTranscriptionBatch(StrictModel):
    sources: list[SourceTranscription] = Field(default_factory=list, max_length=20)


class BatchExtraction(StrictModel):
    groups: list[ResultGroup] = Field(default_factory=list, max_length=100)
    encounters: list[VisitDraft] = Field(default_factory=list, max_length=100)
    excluded_sources: list[ExcludedSource] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)
    reviewed: bool = False


class SaveBatchDraft(StrictModel):
    expected_version: int
    payload: BatchExtraction
    care_targets: dict[str, CareTarget] | None = None
    care_context: UploadCareIntent | None = None


class BatchConfirm(StrictModel):
    expected_version: int


def validate_sources(payload: BatchExtraction, source_ids: set[str], *, confirm: bool = False) -> None:
    group_ids = [g.id for g in payload.groups]
    visits = {v.id: v for v in payload.encounters}
    if len(set(group_ids)) != len(group_ids) or len(visits) != len(payload.encounters):
        raise ValueError('分组编号重复')
    used = set()
    for group in payload.groups:
        ids = set(group.source_ids)
        if not ids <= source_ids or len(ids) != len(group.source_ids):
            raise ValueError('分组引用了不存在或重复的来源')
        if group.encounter_id and group.encounter_id not in visits:
            raise ValueError('分组关联的就诊不存在')
        if confirm and group.kind == 'medication' and len(group.medications) != 1:
            raise ValueError('同一药品组应包含一种药品；不同药品请拆分为不同组')
        for ref in group.evidence:
            if ref.source_id not in ids:
                raise ValueError('字段依据不属于当前分组，请重新核对')
        for lab in group.lab_results:
            if lab.source_id and lab.source_id not in ids:
                raise ValueError('检验结果来源不属于当前分组，请重新核对')
        for med in group.medications:
            for package in med.packages:
                if not set(package.source_ids) <= ids:
                    raise ValueError('药品包装引用不属于当前分组')
        used |= ids
    excluded = [x.source_id for x in payload.excluded_sources]
    if len(set(excluded)) != len(excluded) or set(excluded) & used or used | set(excluded) != source_ids:
        raise ValueError('有来源未分组，或排除来源与已有分组冲突；请逐项处置')
    if confirm:
        if not payload.reviewed or not payload.groups:
            raise ValueError('请先核对分组、字段和关联，再勾选核对完成')
        # Reviewed associations may span hospitals. Each document retains its
        # original hospital; automatic grouping must still require evidence.
