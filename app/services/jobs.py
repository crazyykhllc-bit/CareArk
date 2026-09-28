import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Attachment, ExtractionDraft, ExtractionJob
from app.services.extraction import ExtractionError, Extractor
from app.services.preprocess import DocumentPreprocessor
from app.services.storage import ObjectStorage


class JobProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        extractor: Extractor,
        settings: Settings,
    ):
        self.session_factory = session_factory
        self.storage = storage
        self.extractor = extractor
        self.settings = settings
        self.preprocessor = DocumentPreprocessor(settings.model_max_pages)

    async def claim_next(self, worker_id: str) -> UUID | None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as db:
            job = await db.scalar(
                select(ExtractionJob)
                .where(
                    ExtractionJob.status == "uploaded",
                    or_(ExtractionJob.next_attempt_at.is_(None), ExtractionJob.next_attempt_at <= now),
                )
                .order_by(ExtractionJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not job:
                return None
            job.claimed_by = worker_id
            job.lease_expires_at = now + timedelta(minutes=10)
            job.status = "preprocessing"
            await db.commit()
            return job.id

    async def process(self, job_id: UUID) -> None:
        job_id = UUID(str(job_id))
        temp_path = None
        async with self.session_factory() as db:
            job = await db.get(ExtractionJob, job_id)
            if not job or job.status in {"pending_confirmation", "archived"}:
                return
            attachment = await db.get(Attachment, job.attachment_id)
            if not attachment:
                await self._fail(db, job, "attachment_missing", "原始文件不存在", False)
                return
            try:
                job.status = "preprocessing"
                await db.commit()
                stream = await self.storage.get(attachment.object_key)
                data = await asyncio.to_thread(stream.read)
                close = getattr(stream, "close", None)
                if close:
                    await asyncio.to_thread(close)
                suffix = Path(attachment.filename).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
                    temp.write(data)
                    temp_path = temp.name
                prepared = await asyncio.to_thread(self.preprocessor.prepare, Path(temp_path), attachment.mime_type)
                job.status = "extracting"
                await db.commit()
                draft_data = await self.extractor.extract(prepared)
                existing = await db.scalar(select(ExtractionDraft).where(ExtractionDraft.job_id == job.id))
                if not existing:
                    db.add(ExtractionDraft(owner_id=job.owner_id, job_id=job.id, payload=draft_data.model_dump(mode="json")))
                job.status = "pending_confirmation"
                job.provider = self.settings.model_provider
                job.model_name = getattr(self.extractor, 'last_model_name', None) or self.settings.model_name or "fake"
                job.error_code = None
                job.error_message = None
                await db.commit()
            except ExtractionError as error:
                await self._fail(db, job, error.code, str(error), error.retryable)
            except (ValueError, OSError) as error:
                await self._fail(db, job, "preprocess_failed", str(error), False)
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)

    async def _fail(self, db: AsyncSession, job: ExtractionJob, code: str, message: str, retryable: bool) -> None:
        job.retry_count += 1
        job.error_code = code
        job.error_message = message[:500]
        if retryable and job.retry_count <= self.settings.model_max_retries:
            job.status = "uploaded"
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=2 ** job.retry_count)
        else:
            job.status = "failed"
            job.next_attempt_at = None
        await db.commit()
