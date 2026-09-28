from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import get_account_user
from app.models import Session, User
from app.security import hash_token
from app.services import auth as auth_service

router = APIRouter(prefix="/api")


class Credentials(BaseModel):
    email: str
    password: str


class InvitationRegistration(BaseModel):
    token: str
    password: str


def user_json(user: User) -> dict:
    return {"id": str(user.id), "email": user.email, "role": user.role, "is_active": user.is_active}


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/",
    )


@router.get("/setup/status")
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    return {"required": (await db.scalar(select(func.count()).select_from(User))) == 0}


@router.post("/setup/admin", status_code=201)
async def create_admin(data: Credentials, response: Response, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    user, token = await auth_service.setup_admin(db, data.email, data.password, settings)
    set_session_cookie(response, token, settings)
    return user_json(user)


@router.post("/auth/login")
async def login(data: Credentials, response: Response, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    user, token = await auth_service.login(db, data.email, data.password, settings)
    set_session_cookie(response, token, settings)
    return user_json(user)


@router.post("/auth/register/invitation", status_code=201)
async def register(data: InvitationRegistration, response: Response, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    user, token = await auth_service.register_from_invitation(db, data.token, data.password, settings)
    set_session_cookie(response, token, settings)
    return user_json(user)


@router.get("/auth/me")
async def me(user: User = Depends(get_account_user)) -> dict:
    return user_json(user)


@router.post("/auth/logout", status_code=204)
async def logout(
    response: Response,
    token: str | None = Cookie(default=None, alias="health_session"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    if token:
        await db.execute(update(Session).where(Session.token_hash == hash_token(token)).values(revoked_at=datetime.now(timezone.utc)))
        await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.status_code = 204
    return response
