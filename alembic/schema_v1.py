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


class Medication(IdMixin, OwnedMixin, Base):
    __tablename__ = "medications"
    __table_args__ = (UniqueConstraint("owner_id", "drug_key", name="uq_medication_owner_drug_key"),)

    drug_key: Mapped[str] = mapped_column(String(400))
    name: Mapped[str] = mapped_column(String(300))
    generic_name: Mapped[str | None] = mapped_column(String(300))
    brand_name: Mapped[str | None] = mapped_column(String(300))
    strength: Mapped[str | None] = mapped_column(String(200))
    dosage_form: Mapped[str | None] = mapped_column(String(100))
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
