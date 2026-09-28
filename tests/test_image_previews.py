from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.services.storage import get_storage
from tests.test_uploads import FakeStorage, setup_admin


class TrackedStorage(FakeStorage):
    def __init__(self):
        super().__init__()
        self.reads = []

    async def get(self, key):
        self.reads.append(key)
        return await super().get(key)


def scan_bytes():
    # Camera-like high entropy image, with an orientation tag, never a real record.
    image = Image.effect_noise((3000, 2000), 70).convert("RGB")
    output = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    image.save(output, "PNG", exif=exif)
    return output.getvalue()


def test_private_preview_is_smaller_oriented_cached_and_keeps_original(app):
    storage = TrackedStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    original = scan_bytes()
    with TestClient(app) as client:
        setup_admin(client)
        attachment_id = client.post('/api/uploads', files={'file': ('scan.png', original, 'image/png')}).json()['attachment_id']
        original_key = storage.last_key
        url = f'/api/attachments/{attachment_id}/preview'
        first = client.get(url)
        assert first.status_code == 200
        assert first.headers['content-type'] == 'image/jpeg'
        assert 'private' in first.headers['cache-control']
        assert 'must-revalidate' in first.headers['cache-control']
        assert first.headers['vary'] == 'Cookie'
        with Image.open(BytesIO(first.content)) as image:
            assert image.height == 2200
            assert image.width < image.height  # EXIF orientation applied.
        assert len(first.content) < len(original) / 2
        assert storage.objects[original_key] == original
        second = client.get(url)
        assert second.content == first.content
        assert storage.reads.count(original_key) == 1
        reads = len(storage.reads)
        conditional = client.get(url, headers={'If-None-Match': first.headers['etag']})
        assert conditional.status_code == 304
        assert conditional.content == b''
        assert len(storage.reads) == reads
        thumb = client.get(f'{url}?size=320')
        with Image.open(BytesIO(thumb.content)) as image:
            assert max(image.size) == 320
        assert client.get(f'{url}?size=1000').status_code == 422
        assert client.get(f'/api/attachments/{attachment_id}/content').content == original
        invitation = client.post('/api/admin/invitations', json={'email':'other@example.test','expires_in_hours':24}).json()
        etag = first.headers['etag']
    reads = len(storage.reads)
    with TestClient(app) as other:
        assert other.get(url, headers={'If-None-Match':etag}).status_code == 401
        other.post('/api/auth/register/invitation', json={'token':invitation['token'],'password':'Correct-Horse-43'})
        assert other.get(url, headers={'If-None-Match':etag}).status_code == 404
    assert len(storage.reads) == reads


def test_corrupt_image_does_not_cache_a_broken_derivative(app):
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as client:
        setup_admin(client)
        result = client.post('/api/uploads', files={'file':('bad.png',b'invalid','image/png')}).json()
        assert client.get(f"/api/attachments/{result['attachment_id']}/preview").status_code == 422
        assert len(storage.objects) == 1


def test_batch_api_advertises_preview_links_without_changing_content_url(client,app):
    from tests.test_batches import create_batch
    batch, _ = create_batch(client,app,count=1)
    attachment_id = batch['files'][0]['attachment_id']
    assert batch['files'][0]['preview_url'] == f'/api/attachments/{attachment_id}/preview'
    assert batch['files'][0]['thumbnail_url'].endswith('/preview?size=320')
    assert batch['files'][0]['content_url'].endswith('/content')
