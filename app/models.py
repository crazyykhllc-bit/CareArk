import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB


JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OwnedMixin:
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class User(IdMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    dashboard_customized: Mapped[bool] = mapped_column(Boolean, default=False)
    managed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    profile_name: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Invitation(IdMixin, Base):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(IdMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    active_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(IdMixin, OwnedMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_owner_date", "owner_id", "primary_date"),)

    document_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    primary_date: Mapped[date | None] = mapped_column(Date)
    primary_date_raw: Mapped[str | None] = mapped_column(String(100))
    hospital: Mapped[str | None] = mapped_column(String(300))
    department: Mapped[str | None] = mapped_column(String(200))
    doctor: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    key_information: Mapped[list] = mapped_column(JsonType, default=list)
    parsed_content: Mapped[str | None] = mapped_column(Text)
    extraction_metadata: Mapped[dict] = mapped_column(JsonType, default=dict)
    type_specific_data: Mapped[dict] = mapped_column(JsonType, default=dict)
    patient_scope: Mapped[str] = mapped_column(String(20), default="unconfirmed", index=True)
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("encounters.id", ondelete="SET NULL"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Attachment(IdMixin, OwnedMixin, Base):
    __tablename__ = "attachments"

    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    page_count: Mapped[int | None] = mapped_column(Integer)


class LabResult(IdMixin, OwnedMixin, Base):
    __tablename__ = "lab_results"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    result: Mapped[str | None] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(100))
    reference_range: Mapped[str | None] = mapped_column(String(200))
    flag: Mapped[str | None] = mapped_column(String(30))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    analyte_key: Mapped[str | None] = mapped_column(String(200), index=True)
    specimen: Mapped[str | None] = mapped_column(String(200))
    condition: Mapped[str | None] = mapped_column(String(200))
    observed_date: Mapped[date | None] = mapped_column(Date, index=True)
    timepoint_minutes: Mapped[int | None] = mapped_column(Integer)
    test_session_key: Mapped[str | None] = mapped_column(String(200), index=True)
    test_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("test_sessions.id", ondelete="SET NULL"), index=True)
    source_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_units.id", ondelete="SET NULL"), index=True)
    result_type: Mapped[str] = mapped_column(String(20), default="unknown")
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)


class Medication(IdMixin, OwnedMixin, Base):
    __tablename__ = "medications"
    __table_args__ = (UniqueConstraint("owner_id", "drug_key", name="uq_medication_owner_drug_key"),)

    drug_key: Mapped[str] = mapped_column(String(400))
    name: Mapped[str] = mapped_column(String(300))
    generic_name: Mapped[str | None] = mapped_column(String(300))
    brand_name: Mapped[str | None] = mapped_column(String(300))
    strength: Mapped[str | None] = mapped_column(String(200))
    dosage_form: Mapped[str | None] = mapped_column(String(100))
    manufacturer: Mapped[str | None] = mapped_column(String(300))
    approval_number: Mapped[str | None] = mapped_column(String(200))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="备用药")
    dose_each_time: Mapped[str | None] = mapped_column(String(200))
    frequency: Mapped[str | None] = mapped_column(String(200))
    timing: Mapped[str | None] = mapped_column(String(200))
    route: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[date | None] = mapped_column(Date)
    planned_end_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class MedicationSource(IdMixin, OwnedMixin, Base):
    __tablename__ = "medication_sources"

    medication_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    instructions: Mapped[str | None] = mapped_column(Text)
    purpose_text: Mapped[str | None] = mapped_column(Text)
    source_data: Mapped[dict] = mapped_column(JsonType, default=dict)


class MedicationEvent(IdMixin, OwnedMixin, Base):
    __tablename__ = "medication_events"

    medication_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(20))
    event_date: Mapped[date] = mapped_column(Date)
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    dose_each_time: Mapped[str | None] = mapped_column(String(200))
    frequency: Mapped[str | None] = mapped_column(String(200))
    timing: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)


class ExtractionJob(IdMixin, OwnedMixin, Base):
    __tablename__ = "extraction_jobs"

    attachment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="uploaded", index=True)
    provider: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(200))
    schema_version: Mapped[str] = mapped_column(String(30), default="1.0")
    prompt_version: Mapped[str] = mapped_column(String(30), default="1.0")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))


class ExtractionDraft(IdMixin, OwnedMixin, Base):
    __tablename__ = "extraction_drafts"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extraction_jobs.id", ondelete="CASCADE"), unique=True)
    payload: Mapped[dict] = mapped_column(JsonType)
    revised_payload: Mapped[dict | None] = mapped_column(JsonType)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadCareContext(IdMixin, OwnedMixin, Base):
    __tablename__ = "upload_care_contexts"
    __table_args__ = (UniqueConstraint("owner_id", "intent_key", name="uq_upload_care_intent"),)
    intent_key: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(24), default="small")
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("care_topics.id", ondelete="RESTRICT"), nullable=True, index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True, index=True)


class UploadBatch(IdMixin, OwnedMixin, Base):
    __tablename__ = "upload_batches"
    care_context_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload_care_contexts.id", ondelete="RESTRICT"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="receiving", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    grouping: Mapped[dict] = mapped_column(JsonType, default=dict)
    payload: Mapped[dict | None] = mapped_column(JsonType)
    original_payload: Mapped[dict | None] = mapped_column(JsonType)
    result: Mapped[dict | None] = mapped_column(JsonType)
    error_message: Mapped[str | None] = mapped_column(String(500))
    attempt_token: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class BatchFile(IdMixin, OwnedMixin, Base):
    __tablename__ = "batch_files"
    __table_args__ = (UniqueConstraint("batch_id", "client_file_id", name="uq_batch_client_file"),)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload_batches.id", ondelete="CASCADE"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"))
    client_file_id: Mapped[str] = mapped_column(String(100))
    ordinal: Mapped[int] = mapped_column(Integer)


class SourceUnit(IdMixin, OwnedMixin, Base):
    __tablename__ = "source_units"
    __table_args__ = (UniqueConstraint("batch_id", "attachment_id", "ordinal", name="uq_batch_source_unit"),)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload_batches.id", ondelete="CASCADE"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    page_index: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(600))
    kind: Mapped[str] = mapped_column(String(20))


class DocumentSource(IdMixin, OwnedMixin, Base):
    __tablename__ = "document_sources"
    __table_args__ = (UniqueConstraint("document_id", "source_unit_id", name="uq_document_source_unit"),)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    source_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_units.id", ondelete="CASCADE"))


class Encounter(IdMixin, OwnedMixin, Base):
    __tablename__ = "encounters"
    primary_topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("care_topics.id", ondelete="SET NULL"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    hospital: Mapped[str | None] = mapped_column(String(300))
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    patient_identity: Mapped[str | None] = mapped_column(String(300))
    evidence: Mapped[list] = mapped_column(JsonType, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    event_kind: Mapped[str] = mapped_column(String(24), default="other")
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_basis: Mapped[str] = mapped_column(String(24), default="unknown")
    date_sources: Mapped[list] = mapped_column(JsonType, default=list)
    summary_facts: Mapped[list] = mapped_column(JsonType, default=list)
    milestones: Mapped[list] = mapped_column(JsonType, default=list)
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)


class CareTopic(IdMixin, OwnedMixin, Base):
    __tablename__ = "care_topics"
    name: Mapped[str] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    analysis_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)


class CareTopicEncounter(IdMixin, OwnedMixin, Base):
    __tablename__ = "care_topic_encounters"
    __table_args__ = (UniqueConstraint("topic_id", "encounter_id", name="uq_care_topic_encounter"),)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_topics.id", ondelete="CASCADE"), index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"), index=True)
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict)


class CareTopicExclusion(IdMixin, OwnedMixin, Base):
    __tablename__ = "care_topic_exclusions"
    __table_args__ = (UniqueConstraint("topic_id", "encounter_id", name="uq_care_topic_exclusion"),)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_topics.id", ondelete="CASCADE"), index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"), index=True)


class CareSuggestion(IdMixin, OwnedMixin, Base):
    __tablename__ = "care_suggestions"
    __table_args__ = (UniqueConstraint("owner_id", "dedupe_key", name="uq_care_suggestion_owner_key"),)
    kind: Mapped[str] = mapped_column(String(30))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    source_versions: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CareRevision(IdMixin, OwnedMixin, Base):
    __tablename__ = "care_revisions"
    object_kind: Mapped[str] = mapped_column(String(20), index=True)
    object_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    from_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JsonType)
    changed_fields: Mapped[list] = mapped_column(JsonType, default=list)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class RelatedEncounter(IdMixin, OwnedMixin, Base):
    __tablename__ = "related_encounters"
    __table_args__ = (UniqueConstraint("document_id", "encounter_id", name="uq_related_document_encounter"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id", ondelete="CASCADE"), index=True)


class MedicationPackage(IdMixin, OwnedMixin, Base):
    __tablename__ = "medication_packages"
    medication_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    batch_number: Mapped[str | None] = mapped_column(String(200))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    quantity_raw: Mapped[str | None] = mapped_column(String(200))
    source_data: Mapped[dict] = mapped_column(JsonType, default=dict)


class ReceiptDetail(IdMixin, OwnedMixin, Base):
    __tablename__ = "receipt_details"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True)
    receipt_number: Mapped[str | None] = mapped_column(String(300))
    receipt_identity: Mapped[str | None] = mapped_column(String(128), index=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    insurance_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    personal_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    settlement_time: Mapped[str | None] = mapped_column(String(200))
    payment_method: Mapped[str | None] = mapped_column(String(200))
    line_items: Mapped[list] = mapped_column(JsonType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("receipt_details.id", ondelete="SET NULL"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class MetricDefinition(IdMixin, OwnedMixin, Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (UniqueConstraint("owner_id", "key", name="uq_metric_owner_key"),)
    key: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(300))
    group_name: Mapped[str] = mapped_column(String(100))
    record_type: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str | None] = mapped_column(String(100))
    aliases: Mapped[list] = mapped_column(JsonType, default=list)
    component_labels: Mapped[list] = mapped_column(JsonType, default=list)
    followed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dashboard_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    preset: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class MetricEntry(IdMixin, OwnedMixin, Base):
    __tablename__ = "metric_entries"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key", name="uq_metric_entry_owner_idempotency"),)
    metric_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("metric_definitions.id", ondelete="CASCADE"), index=True)
    record_date: Mapped[date] = mapped_column(Date, index=True)
    raw_value: Mapped[str] = mapped_column(String(500))
    value1: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value2: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    text_value: Mapped[str | None] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(100))
    condition: Mapped[str | None] = mapped_column(String(200))
    review_status: Mapped[str] = mapped_column(String(20), default="confirmed")
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class MetricEntryRevision(IdMixin, OwnedMixin, Base):
    __tablename__ = "metric_entry_revisions"
    metric_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("metric_entries.id", ondelete="CASCADE"), index=True)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    from_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JsonType)
    changed_fields: Mapped[list] = mapped_column(JsonType, default=list)


class TestSession(IdMixin, OwnedMixin, Base):
    __tablename__ = "test_sessions"
    name: Mapped[str] = mapped_column(String(300))
    session_date: Mapped[date | None] = mapped_column(Date, index=True)
    hospital: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TestSessionSource(IdMixin, OwnedMixin, Base):
    __tablename__ = "test_session_sources"
    __table_args__ = (UniqueConstraint("test_session_id", "source_unit_id", name="uq_test_session_source"),)
    test_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_sessions.id", ondelete="CASCADE"), index=True)
    source_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_units.id", ondelete="CASCADE"), index=True)


class DocumentRevision(IdMixin, OwnedMixin, Base):
    __tablename__ = "document_revisions"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    from_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JsonType)
    changed_fields: Mapped[list] = mapped_column(JsonType, default=list)


class MedicationRevision(IdMixin, OwnedMixin, Base):
    __tablename__ = "medication_revisions"
    medication_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    from_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JsonType)
    changed_fields: Mapped[list] = mapped_column(JsonType, default=list)
