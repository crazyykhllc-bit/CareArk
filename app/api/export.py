from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import User
from app.services.exports import create_user_export
from app.services.storage import ObjectStorage, get_storage

router = APIRouter(prefix="/api")


@router.get("/export")
async def export_archive(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
):
    archive = await create_user_export(db, storage, user)
    filename = f"health-archive-{date.today().isoformat()}.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )
