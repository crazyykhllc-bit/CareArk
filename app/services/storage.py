import asyncio
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol

from minio import Minio

from app.config import Settings, get_settings


class ObjectStorage(Protocol):
    async def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> None: ...
    async def get(self, key: str) -> BinaryIO: ...
    async def delete(self, key: str) -> None: ...


class MinioStorage:
    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.client = Minio(
            settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=settings.s3_secure,
        )

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    async def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> None:
        await asyncio.to_thread(self._ensure_bucket)
        stream.seek(0)
        await asyncio.to_thread(self.client.put_object, self.bucket, key, stream, size, content_type=content_type)

    async def get(self, key: str) -> BinaryIO:
        return await asyncio.to_thread(self.client.get_object, self.bucket, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self.bucket, key)


class FileStorage:
    """Store originals under a private local directory in the portable edition."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("无效的资料路径")
        return path

    def _put(self, key: str, stream: BinaryIO, size: int) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        stream.seek(0)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".upload-", delete=False) as output:
                temporary = Path(output.name)
                remaining = size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("资料内容不足")
                    output.write(chunk)
                    remaining -= len(chunk)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def put(self, key: str, stream: BinaryIO, size: int, content_type: str) -> None:
        await asyncio.to_thread(self._put, key, stream, size)

    async def get(self, key: str) -> BinaryIO:
        try:
            return await asyncio.to_thread(self._path(key).open, "rb")
        except FileNotFoundError as error:
            raise KeyError(key) from error

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.storage_backend == "file":
        if not settings.file_storage_root:
            raise ValueError("FILE_STORAGE_ROOT 尚未设置")
        return FileStorage(Path(settings.file_storage_root))
    if settings.storage_backend != "minio":
        raise ValueError("不支持的存储方式")
    return MinioStorage(settings)
