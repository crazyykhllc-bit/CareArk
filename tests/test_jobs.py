from io import BytesIO

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models import Attachment, ExtractionDraft, ExtractionJob, User
from app.services.extraction import FakeExtractor, OpenAICompatibleExtractor
from app.services.jobs import JobProcessor

from tests.test_extraction import VALID_DRAFT


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    async def put(self, key, stream, size, content_type):
        self.objects[key] = stream.read()

    async def get(self, key):
        return BytesIO(self.objects[key])

    async def delete(self, key):
        self.objects.pop(key, None)


async def create_uploaded_job(session_factory, storage):
    async with session_factory() as db:
        user = User(email="worker@example.test", password_hash="hash", role="user")
        db.add(user)
        await db.flush()
        attachment = Attachment(
            owner_id=user.id,
            filename="report.png",
            mime_type="image/png",
            size_bytes=8,
            sha256="0" * 64,
            object_key=f"users/{user.id}/report.png",
        )
        db.add(attachment)
        await db.flush()
        job = ExtractionJob(owner_id=user.id, attachment_id=attachment.id, status="uploaded")
        db.add(job)
        await db.commit()
        storage.objects[attachment.object_key] = make_png()
        return job.id


def make_png():
    from PIL import Image
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, "PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_completed_job_does_not_create_second_draft(session_factory):
    storage = MemoryStorage()
    job_id = await create_uploaded_job(session_factory, storage)
    processor = JobProcessor(session_factory, storage, FakeExtractor(VALID_DRAFT), Settings())

    await processor.process(job_id)
    await processor.process(job_id)

    async with session_factory() as db:
        job = await db.get(ExtractionJob, job_id)
        count = await db.scalar(select(func.count()).select_from(ExtractionDraft).where(ExtractionDraft.job_id == job_id))
        assert job.status == "pending_confirmation"
        assert count == 1


@pytest.mark.asyncio
async def test_unconfigured_model_marks_job_failed(session_factory):
    storage = MemoryStorage()
    job_id = await create_uploaded_job(session_factory, storage)
    extractor = OpenAICompatibleExtractor(Settings(model_api_key="", model_name=""))
    processor = JobProcessor(session_factory, storage, extractor, Settings())

    await processor.process(job_id)

    async with session_factory() as db:
        job = await db.get(ExtractionJob, job_id)
        assert job.status == "failed"
        assert job.error_code == "model_not_configured"
