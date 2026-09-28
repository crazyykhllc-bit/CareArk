from io import BytesIO

from fastapi.testclient import TestClient

from app.services.storage import get_storage


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.last_key = None

    async def put(self, key, stream, size, content_type):
        self.last_key = key
        self.objects[key] = stream.read()

    async def get(self, key):
        return BytesIO(self.objects[key])

    async def delete(self, key):
        self.objects.pop(key, None)


def setup_admin(client, email="admin@example.test"):
    response = client.post("/api/setup/admin", json={"email": email, "password": "Correct-Horse-42"})
    assert response.status_code == 201
    return response.json()


def test_upload_creates_private_attachment_and_job(app):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as client:
        user = setup_admin(client)
        response = client.post(
            "/api/uploads",
            files={"file": ("report.png", b"png-data", "image/png")},
        )

    assert response.status_code == 202
    assert response.json()["job_status"] == "uploaded"
    assert storage.last_key.startswith(f"users/{user['id']}/")


def test_other_user_cannot_open_attachment(app):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as admin_client:
        setup_admin(admin_client)
        invitation = admin_client.post(
            "/api/admin/invitations",
            json={"email": "user@example.test", "expires_in_hours": 24},
        ).json()
        uploaded = admin_client.post(
            "/api/uploads",
            files={"file": ("report.png", b"owner-data", "image/png")},
        ).json()
    with TestClient(app) as other_client:
        other_client.post(
            "/api/auth/register/invitation",
            json={"token": invitation["token"], "password": "Correct-Horse-43"},
        )
        response = other_client.get(f"/api/attachments/{uploaded['attachment_id']}/content")

    assert response.status_code == 404


def test_rejects_unsupported_file_type(app):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as client:
        setup_admin(client)
        response = client.post(
            "/api/uploads",
            files={"file": ("program.exe", b"binary", "application/octet-stream")},
        )

    assert response.status_code == 415
    assert storage.objects == {}
