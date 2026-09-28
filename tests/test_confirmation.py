import asyncio
import copy
import uuid

from app.models import Attachment, ExtractionDraft, ExtractionJob
from tests.test_extraction import VALID_DRAFT
from tests.test_uploads import FakeStorage, setup_admin
from app.services.storage import get_storage


async def create_pending_draft(session_factory, owner_id):
    owner_id = uuid.UUID(str(owner_id))
    async with session_factory() as db:
        attachment = Attachment(
            owner_id=owner_id,
            filename="report.png",
            mime_type="image/png",
            size_bytes=8,
            sha256="1" * 64,
            object_key=f"users/{owner_id}/{uuid.uuid4()}-report.png",
        )
        db.add(attachment)
        await db.flush()
        job = ExtractionJob(owner_id=owner_id, attachment_id=attachment.id, status="pending_confirmation")
        db.add(job)
        await db.flush()
        draft = ExtractionDraft(owner_id=owner_id, job_id=job.id, payload=VALID_DRAFT)
        db.add(draft)
        await db.commit()
        return draft.id


def test_unconfirmed_draft_is_absent_then_confirmed_atomically(client, app, session_factory):
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    user = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, user["id"]))

    assert client.get("/api/documents").json()["items"] == []
    pending = client.get("/api/drafts").json()["items"]
    assert pending[0]["id"] == str(draft_id)
    attachment = pending[0]["attachment"]
    assert attachment["filename"] == "report.png"
    assert attachment["mime_type"] == "image/png"
    assert attachment["content_url"] == f"/api/drafts/{draft_id}/attachment"
    assert attachment["preview_url"].startswith('/api/attachments/')
    assert attachment["thumbnail_url"].endswith('/preview?size=320')
    preview = client.get(f"/api/drafts/{draft_id}/attachment", follow_redirects=False)
    assert preview.status_code == 307
    assert "/api/attachments/" in preview.headers["location"]

    response = client.post(
        f"/api/drafts/{draft_id}/confirm",
        json={"payload": VALID_DRAFT},
    )

    assert response.status_code == 201
    detail = client.get(f"/api/documents/{response.json()['document_id']}").json()
    assert detail["title"] == "血常规"
    assert detail["document_type"] == "检验报告"
    assert client.get("/api/drafts").json()["items"] == []


def test_other_user_cannot_confirm_draft(app, session_factory):
    from fastapi.testclient import TestClient

    with TestClient(app) as admin:
        owner = setup_admin(admin)
        invitation = admin.post("/api/admin/invitations", json={"email": "other@example.test"}).json()
        draft_id = asyncio.run(create_pending_draft(session_factory, owner["id"]))
    with TestClient(app) as other:
        other.post("/api/auth/register/invitation", json={"token": invitation["token"], "password": "Correct-Horse-43"})
        response = other.post(f"/api/drafts/{draft_id}/confirm", json={"payload": VALID_DRAFT})

    assert response.status_code == 404


def test_confirmation_rejects_nonfinite_amount_and_unowned_source(client, session_factory):
    user = setup_admin(client)
    amount_draft = asyncio.run(create_pending_draft(session_factory, user['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['document']['amount'] = 'NaN'
    assert client.post(f'/api/drafts/{amount_draft}/confirm', json={'payload': payload}).status_code == 422

    source_draft = asyncio.run(create_pending_draft(session_factory, user['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['lab_results'] = [{'name': '合成项目', 'result': '1', 'source_id': str(uuid.uuid4())}]
    assert client.post(f'/api/drafts/{source_draft}/confirm', json={'payload': payload}).status_code == 422


def test_confirmation_accepts_yuan_suffix_without_manual_edit(client, session_factory):
    user = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, user['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['document']['amount'] = '80,936.32元'
    response = client.post(f'/api/drafts/{draft_id}/confirm', json={'payload': payload})
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/documents/{response.json()['document_id']}").json()
    assert detail['amount'] == '80936.32'


def test_confirmed_unknown_lab_is_available_as_metric_without_manual_setup(client, session_factory):
    user = setup_admin(client)
    draft_id = asyncio.run(create_pending_draft(session_factory, user['id']))
    payload = copy.deepcopy(VALID_DRAFT)
    payload['document']['patient_scope'] = 'self'
    payload['lab_results'] = [{
        'name': '胱抑素 C', 'analyte_key': 'cystatin_c', 'result': '0.91', 'unit': 'mg/L',
        'observed_date': '2026-09-06', 'result_type': 'numeric', 'review_status': 'confirmed',
    }]

    response = client.post(f'/api/drafts/{draft_id}/confirm', json={'payload': payload})

    assert response.status_code == 201
    metrics = client.get('/api/metrics').json()['items']
    assert any(item['key'] == 'lab:cystatin_c' for item in metrics)
