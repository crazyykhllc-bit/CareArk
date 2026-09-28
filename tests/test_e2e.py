import asyncio
import copy
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.services.extraction import FakeExtractor
from app.services.jobs import JobProcessor
from app.services.storage import get_storage
from tests.test_extraction import VALID_DRAFT
from tests.test_uploads import FakeStorage, setup_admin


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (40, 40), "white").save(output, "PNG")
    return output.getvalue()


def test_upload_extract_confirm_and_isolate_two_users(client, app, session_factory):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    setup_admin(client)
    invitation = client.post("/api/admin/invitations", json={"email": "member@example.test"}).json()
    uploaded = client.post(
        "/api/uploads",
        files={"file": ("report.png", png_bytes(), "image/png")},
    ).json()

    payload = copy.deepcopy(VALID_DRAFT)
    payload["lab_results"] = [{
        "name": "白细胞", "result": "5.0", "unit": "10^9/L",
        "reference_range": "3.5-9.5", "flag": None,
        "source_ref": {"page": 1, "quote": "白细胞 5.0"},
    }]
    payload["medications"] = [{
        "drug_key": "demo-drug", "name": "示例药品", "generic_name": None,
        "brand_name": None, "strength": "10mg", "dosage_form": "片剂",
        "expiry_date": "2030-01-01", "quantity": "10片", "route": "口服",
        "instructions": "包装原文：每次一片", "purpose_text": None, "source_refs": [],
    }]
    processor = JobProcessor(session_factory, storage, FakeExtractor(payload), Settings(model_name="fake"))
    asyncio.run(processor.process(uploaded["job_id"]))

    assert client.get("/api/documents").json()["items"] == []
    draft = client.get("/api/drafts").json()["items"][0]
    confirmed = client.post(f"/api/drafts/{draft['id']}/confirm", json={"payload": draft["payload"]})
    assert confirmed.status_code == 201
    document_id = confirmed.json()["document_id"]
    detail = client.get(f"/api/documents/{document_id}").json()
    assert detail["lab_results"][0]["result"] == "5.0"
    assert client.get("/api/medications").json()["items"][0]["name"] == "示例药品"

    with TestClient(app) as other:
        other.post("/api/auth/register/invitation", json={
            "token": invitation["token"], "password": "Correct-Horse-43",
        })
        assert other.get("/api/documents").json()["items"] == []
        assert other.get(f"/api/documents/{document_id}").status_code == 404
