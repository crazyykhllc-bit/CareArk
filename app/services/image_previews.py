"""Private, persistent display derivatives. Original attachments stay untouched."""
import asyncio
import io
from weakref import WeakValueDictionary

from minio.error import S3Error
from PIL import Image, ImageOps

PREVIEW_VERSION = "v1"
DISPLAY_SIZE = 2200
THUMB_SIZE = 320
_locks = WeakValueDictionary()


def preview_urls(attachment):
    if not attachment.mime_type.startswith("image/"):
        return {}
    base = f"/api/attachments/{attachment.id}/preview"
    return {"preview_url": base, "thumbnail_url": f"{base}?size={THUMB_SIZE}"}


def _read_and_close(stream):
    try:
        return stream.read()
    finally:
        stream.close()
        if hasattr(stream, "release_conn"):
            stream.release_conn()


def make_preview(data, size):
    with Image.open(io.BytesIO(data)) as original:
        image = ImageOps.exif_transpose(original)
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, "white")
            canvas.paste(rgba, mask=rgba.getchannel("A"))
            image = canvas
        else:
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, "JPEG", quality=90 if size == DISPLAY_SIZE else 80,
                   subsampling=0, optimize=True, progressive=True)
        return output.getvalue()


async def get_preview(storage, attachment, size):
    key = f"{attachment.object_key}.preview-{PREVIEW_VERSION}-{size}.jpg"
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        try:
            stream = await storage.get(key)
        except KeyError:  # In-memory storage used by tests.
            stream = None
        except S3Error as error:
            if error.code not in ("NoSuchKey", "NoSuchObject"):
                raise
            stream = None
        if stream is not None:
            return await asyncio.to_thread(_read_and_close, stream)
        original = await storage.get(attachment.object_key)
        data = await asyncio.to_thread(_read_and_close, original)
        preview = await asyncio.to_thread(make_preview, data, size)
        await storage.put(key, io.BytesIO(preview), len(preview), "image/jpeg")
        return preview
