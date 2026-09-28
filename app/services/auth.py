from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Invitation, Session, User
from app.security import hash_password, hash_token, new_token, verify_password


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or len(normalized) > 320:
        raise HTTPException(422, "请输入有效邮箱")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(422, "密码至少需要 8 个字符")


async def create_session(db: AsyncSession, user: User, settings: Settings) -> str:
    raw = new_token()
    db.add(Session(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours),
    ))
    await db.flush()
    return raw


async def setup_admin(db: AsyncSession, email: str, password: str, settings: Settings) -> tuple[User, str]:
    validate_password(password)
    if (await db.scalar(select(func.count()).select_from(User))) > 0:
        raise HTTPException(409, "系统已完成初始化")
    user = User(email=normalize_email(email), password_hash=hash_password(password), role="admin")
    db.add(user)
    await db.flush()
    token = await create_session(db, user, settings)
    await db.commit()
    return user, token


async def login(db: AsyncSession, email: str, password: str, settings: Settings) -> tuple[User, str]:
    user = await db.scalar(select(User).where(User.email == normalize_email(email)))
    if not user or not user.is_active or not verify_password(user.password_hash, password):
        raise HTTPException(401, "邮箱或密码错误")
    token = await create_session(db, user, settings)
    await db.commit()
    return user, token


async def create_invitation(db: AsyncSession, creator: User, email: str, expires_in_hours: int) -> tuple[Invitation, str]:
    raw = new_token()
    invitation = Invitation(
        email=normalize_email(email),
        token_hash=hash_token(raw),
        created_by_id=creator.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    return invitation, raw


async def register_from_invitation(db: AsyncSession, token: str, password: str, settings: Settings) -> tuple[User, str]:
    validate_password(password)
    invitation = await db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    now = datetime.now(timezone.utc)
    if not invitation or invitation.used_at or invitation.revoked_at:
        raise HTTPException(409, "邀请无效或已使用")
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(409, "邀请已过期")
    if await db.scalar(select(User).where(User.email == invitation.email)):
        raise HTTPException(409, "该邮箱已注册")
    user = User(email=invitation.email, password_hash=hash_password(password), role="user")
    db.add(user)
    invitation.used_at = now
    await db.flush()
    raw = await create_session(db, user, settings)
    await db.commit()
    return user, raw
