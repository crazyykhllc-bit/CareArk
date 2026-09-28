import hashlib
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models import Attachment, ExtractionJob, User
from app.services.storage import ObjectStorage, get_storage
from app.services.image_previews import DISPLAY_SIZE, THUMB_SIZE, PREVIEW_VERSION, get_preview

router = APIRouter(prefix="/api")

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "application/pdf", "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


@router.post("/uploads", status_code=202)
async def upload(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> dict:
    mime_type = (file.content_type or "").lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(415, "不支持这种文件格式")

    digest = hashlib.sha256()
    size = 0
    spool = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > settings.upload_max_bytes:
            spool.close()
            raise HTTPException(413, "文件超过上传大小限制")
        digest.update(chunk)
        spool.write(chunk)
    spool.seek(0)

    attachment_id = uuid.uuid4()
    suffix = (file.filename or "upload").rsplit(".", 1)[-1].lower()
    object_key = f"users/{user.id}/{attachment_id}.{suffix}"
    try:
        await storage.put(object_key, spool, size, mime_type)
        attachment = Attachment(
            id=attachment_id,
            owner_id=user.id,
            filename=file.filename or "未命名文件",
            mime_type=mime_type,
            size_bytes=size,
            sha256=digest.hexdigest(),
            object_key=object_key,
        )
        job = ExtractionJob(owner_id=user.id, attachment_id=attachment_id, status="uploaded")
        db.add_all([attachment, job])
        await db.commit()
        await db.refresh(job)
    except Exception:
        await db.rollback()
        await storage.delete(object_key)
        raise
    finally:
        spool.close()
    return {"attachment_id": str(attachment.id), "job_id": str(job.id), "job_status": job.status}


@router.get("/attachments/{attachment_id}/content")
async def attachment_content(
    attachment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
):
    attachment = await db.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.owner_id == user.id))
    if not attachment:
        raise HTTPException(404, "附件不存在")
    stream = await storage.get(attachment.object_key)
    headers = {"Content-Disposition": f'inline; filename="{attachment.id}"', "Cache-Control": "private, no-store"}
    return StreamingResponse(stream, media_type=attachment.mime_type, headers=headers)


@router.get("/attachments/{attachment_id}/preview")
async def attachment_preview(
    attachment_id: uuid.UUID,
    request: Request,
    size: int = Query(DISPLAY_SIZE, ge=THUMB_SIZE, le=DISPLAY_SIZE),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
):
    attachment = await db.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.owner_id == user.id))
    if not attachment:
        raise HTTPException(404, "附件不存在")
    if size not in (DISPLAY_SIZE, THUMB_SIZE) or not attachment.mime_type.startswith("image/"):
        raise HTTPException(422, "该附件不支持图片预览")
    etag = f'"preview-{PREVIEW_VERSION}-{attachment.sha256}-{size}"'
    # Always authenticate and check ownership, including conditional requests.
    headers = {"Cache-Control": "private, max-age=0, must-revalidate", "ETag": etag,
               "Vary": "Cookie", "X-Content-Type-Options": "nosniff"}
    matches = {tag.strip().removeprefix("W/") for tag in request.headers.get("if-none-match", "").split(",")}
    if etag in matches or "*" in matches:
        return Response(status_code=304, headers=headers)
    try:
        data = await get_preview(storage, attachment, size)
    except (OSError, ValueError) as error:
        raise HTTPException(422, "无法生成图片预览，请查看原件") from error
    return Response(data, media_type="image/jpeg", headers=headers)


@router.get("/jobs/{job_id}")
async def job_status(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await db.scalar(select(ExtractionJob).where(ExtractionJob.id == job_id, ExtractionJob.owner_id == user.id))
    if not job:
        raise HTTPException(404, "解析任务不存在")
    return {
        "id": str(job.id),
        "status": job.status,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "retry_count": job.retry_count,
    }


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await db.scalar(select(ExtractionJob).where(ExtractionJob.id == job_id, ExtractionJob.owner_id == user.id))
    if not job:
        raise HTTPException(404, "解析任务不存在")
    if job.status != "failed":
        raise HTTPException(409, "当前任务不需要重试")
    job.status = "uploaded"
    job.retry_count = 0
    job.error_code = None
    job.error_message = None
    await db.commit()
    return {"id": str(job.id), "status": job.status}
