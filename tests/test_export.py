import asyncio
import json
import uuid
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import select

from app.models import Attachment, Document, LabResult
from app.services.storage import get_storage
from tests.test_confirmation import create_pending_draft
from tests.test_extraction import VALID_DRAFT
from tests.test_uploads import FakeStorage, setup_admin


async def seed_attachment_object(session_factory, owner_id, storage):
    owner_id = uuid.UUID(owner_id)
    async with session_factory() as db:
        attachment = await db.scalar(select(Attachment).where(Attachment.owner_id == owner_id))
        storage.objects[attachment.object_key] = b"original-medical-file"


async def seed_export_lab(session_factory, owner_id):
    owner_id = uuid.UUID(owner_id)
    async with session_factory() as db:
        document = await db.scalar(select(Document).where(Document.owner_id == owner_id))
        db.add(LabResult(owner_id=owner_id, document_id=document.id, name="合成检验项", result="0",
                         analyte_key="synthetic", condition="空腹", result_type="numeric",
                         review_status="confirmed"))
        await db.commit()


def test_export_contains_manifest_and_current_user_original(client, app, session_factory):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    user = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, user["id"]))
    asyncio.run(seed_attachment_object(session_factory, user["id"], storage))
    client.post(f"/api/drafts/{draft_id}/confirm", json={"payload": VALID_DRAFT})
    asyncio.run(seed_export_lab(session_factory, user["id"]))

    response = client.get("/api/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == "health_archive_export.v5"
        assert manifest["owner"]["email"] == "admin@example.test"
        assert manifest["documents"][0]["title"] == "血常规"
        assert {"receipt_details", "metric_definitions", "metric_entries", "test_sessions",
                "test_session_sources", "document_revisions"} <= set(manifest)
        assert "patient_scope" in manifest["documents"][0]
        assert "condition" in manifest["lab_results"][0]
        assert "attachments/report.png" in archive.namelist()
        assert archive.read("attachments/report.png") == b"original-medical-file"
