from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Attachment, ExtractionDraft, ExtractionJob, User
from app.schemas import ExtractionDraft as DraftPayload
from app.services.confirmation import confirm_draft
from app.services.image_previews import preview_urls

router = APIRouter(prefix="/api/drafts")


class DraftUpdate(BaseModel):
    payload: dict


def draft_json(record: ExtractionDraft, attachment: Attachment | None = None) -> dict:
    result = {
        "id": str(record.id),
        "job_id": str(record.job_id),
        "payload": record.revised_payload or record.payload,
        "status": record.status,
    }
    if attachment:
        result["attachment"] = {
            "filename": attachment.filename,
            "mime_type": attachment.mime_type,
            "content_url": f"/api/drafts/{record.id}/attachment",
            **preview_urls(attachment),
        }
    return result


@router.get("")
async def list_drafts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(
        select(ExtractionDraft, Attachment)
        .join(ExtractionJob, ExtractionJob.id == ExtractionDraft.job_id)
        .join(Attachment, Attachment.id == ExtractionJob.attachment_id)
        .where(
            ExtractionDraft.owner_id == user.id,
            Attachment.owner_id == user.id,
            ExtractionDraft.status == "pending",
        )
        .order_by(ExtractionDraft.created_at.desc())
    )).all()
    return {"items": [draft_json(draft, attachment) for draft, attachment in rows]}


@router.get("/{draft_id}")
async def get_draft(draft_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    row = (await db.execute(
        select(ExtractionDraft, Attachment)
        .join(ExtractionJob, ExtractionJob.id == ExtractionDraft.job_id)
        .join(Attachment, Attachment.id == ExtractionJob.attachment_id)
        .where(
            ExtractionDraft.id == draft_id,
            ExtractionDraft.owner_id == user.id,
            Attachment.owner_id == user.id,
        )
    )).first()
    if not row:
        raise HTTPException(404, "待确认资料不存在")
    draft, attachment = row
    return draft_json(draft, attachment)


@router.get("/{draft_id}/attachment")
async def draft_attachment(draft_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(ExtractionDraft).where(ExtractionDraft.id == draft_id, ExtractionDraft.owner_id == user.id))
    if not row:
        raise HTTPException(404, "待确认资料不存在")
    job = await db.get(ExtractionJob, row.job_id)
    attachment = await db.scalar(select(Attachment).where(Attachment.id == job.attachment_id, Attachment.owner_id == user.id))
    if not attachment:
        raise HTTPException(404, "原始文件不存在")
    return RedirectResponse(f"/api/attachments/{attachment.id}/content")


@router.put("/{draft_id}")
async def update_draft(data: DraftUpdate, draft_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.scalar(select(ExtractionDraft).where(ExtractionDraft.id == draft_id, ExtractionDraft.owner_id == user.id, ExtractionDraft.status == "pending"))
    if not row:
        raise HTTPException(404, "待确认资料不存在")
    validated = DraftPayload.model_validate(data.payload)
    row.revised_payload = validated.model_dump(mode="json")
    await db.commit()
    return draft_json(row)


@router.post("/{draft_id}/confirm", status_code=201)
async def confirm(data: DraftUpdate, draft_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    document = await confirm_draft(db, user, draft_id, data.payload)
    return {"document_id": str(document.id)}
