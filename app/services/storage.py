import asyncio
from functools import lru_cache
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


@lru_cache
def get_storage() -> ObjectStorage:
    return MinioStorage(get_settings())
