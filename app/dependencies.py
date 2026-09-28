from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Session, User
from app.security import hash_token


async def get_auth_context(
    token: str | None = Cookie(default=None, alias="health_session"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> tuple[Session, User]:
    if not token:
        raise HTTPException(401, "请先登录")
    row = await db.execute(
        select(Session, User)
        .join(User, User.id == Session.user_id)
        .where(Session.token_hash == hash_token(token), Session.revoked_at.is_(None), User.is_active.is_(True))
    )
    record = row.first()
    if not record:
        raise HTTPException(401, "登录已失效")
    session, user = record
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "登录已过期")
    session.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return session, user


async def get_account_user(context: tuple[Session, User] = Depends(get_auth_context)) -> User:
    return context[1]


async def get_current_user(context: tuple[Session, User] = Depends(get_auth_context),
                           db: AsyncSession = Depends(get_db)) -> User:
    session, account = context
    if session.active_profile_id is None:
        return account
    profile = await db.scalar(select(User).where(
        User.id == session.active_profile_id, User.managed_by_id == account.id))
    if not profile:
        raise HTTPException(403, "当前档案成员不存在或无权访问")
    return profile


async def require_admin(user: User = Depends(get_account_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
