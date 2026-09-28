from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import require_admin
from app.models import Session, User
from app.services.auth import create_invitation

router = APIRouter(prefix="/api/admin")


class InvitationCreate(BaseModel):
    email: str
    expires_in_hours: int = Field(default=24, ge=1, le=168)


class UserUpdate(BaseModel):
    is_active: bool


@router.post("/invitations", status_code=201)
async def invite(data: InvitationCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    invitation, raw_token = await create_invitation(db, admin, data.email, data.expires_in_hours)
    return {
        "id": str(invitation.id),
        "email": invitation.email,
        "expires_at": invitation.expires_at.isoformat(),
        "token": raw_token,
    }


@router.get("/users")
async def list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    users = (await db.scalars(select(User).where(User.managed_by_id.is_(None)).order_by(User.created_at))).all()
    return {"items": [{
        "id": str(user.id), "email": user.email, "role": user.role,
        "is_active": user.is_active, "created_at": user.created_at.isoformat(),
    } for user in users]}


@router.patch("/users/{user_id}")
async def update_user(data: UserUpdate, user_id: UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, user_id)
    if not user or user.managed_by_id is not None:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id and not data.is_active:
        raise HTTPException(409, "不能禁用当前管理员账号")
    user.is_active = data.is_active
    if not data.is_active:
        await db.execute(update(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
    return {"id": str(user.id), "email": user.email, "role": user.role, "is_active": user.is_active}
