import asyncio
import io

import pytest
from fastapi.testclient import TestClient

from app.services.storage import FileStorage, get_storage


def test_file_storage_round_trip_and_delete(tmp_path):
    storage = FileStorage(tmp_path / "originals")
    key = "users/123/report.pdf"
    content = b"sample medical report"

    async def exercise():
        await storage.put(key, io.BytesIO(content), len(content), "application/pdf")
        stream = await storage.get(key)
        try:
            assert stream.read() == content
        finally:
            stream.close()
        await storage.delete(key)
        with pytest.raises(KeyError):
            await storage.get(key)

    asyncio.run(exercise())


def test_file_storage_rejects_escaping_paths_and_incomplete_writes(tmp_path):
    storage = FileStorage(tmp_path / "originals")

    async def exercise():
        with pytest.raises(ValueError, match="无效的资料路径"):
            await storage.put("../outside", io.BytesIO(b"x"), 1, "text/plain")
        with pytest.raises(ValueError, match="资料内容不足"):
            await storage.put("users/123/incomplete", io.BytesIO(b"x"), 2, "text/plain")

    asyncio.run(exercise())
    assert not (tmp_path / "outside").exists()
    assert not (tmp_path / "originals/users/123/incomplete").exists()


def test_upload_uses_local_original_storage(app, tmp_path):
    class TrackedStorage(FileStorage):
        last_stream = None

        async def get(self, key):
            self.last_stream = await super().get(key)
            return self.last_stream

    storage = TrackedStorage(tmp_path / "originals")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as client:
        setup = client.post("/api/setup/admin", json={
            "email": "desktop@example.test", "password": "Correct-Horse-42",
        })
        assert setup.status_code == 201
        uploaded = client.post("/api/uploads", files={
            "file": ("report.png", b"example-image", "image/png"),
        })
        assert uploaded.status_code == 202
        content = client.get(f"/api/attachments/{uploaded.json()['attachment_id']}/content")
        assert content.status_code == 200
        assert content.content == b"example-image"
        assert storage.last_stream.closed
    assert len(list((tmp_path / "originals").rglob("*.png"))) == 1
