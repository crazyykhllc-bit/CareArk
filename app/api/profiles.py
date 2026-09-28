"""Managed archives owned by a real login account."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_auth_context
from app.models import Session, User


router = APIRouter(prefix='/api/profiles')


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProfileSwitch(BaseModel):
    profile_id: uuid.UUID


def profile_json(profile: User, *, own: bool) -> dict:
    return {'id': str(profile.id), 'name': '我' if own else profile.profile_name,
            'is_self': own}


@router.get('')
async def list_profiles(context: tuple[Session, User] = Depends(get_auth_context),
                        db: AsyncSession = Depends(get_db)) -> dict:
    session, account = context
    managed = (await db.scalars(select(User).where(User.managed_by_id == account.id)
                                .order_by(User.created_at, User.id))).all()
    return {'items': [profile_json(account, own=True),
                      *(profile_json(profile, own=False) for profile in managed)],
            'active_id': str(session.active_profile_id or account.id)}


@router.post('', status_code=201)
async def create_profile(data: ProfileCreate,
                         context: tuple[Session, User] = Depends(get_auth_context),
                         db: AsyncSession = Depends(get_db)) -> dict:
    _session, account = context
    name = data.name.strip()
    if not name or name == '我':
        raise HTTPException(422, '请输入成员名称或称呼')
    profile = User(email=f'managed-{uuid.uuid4().hex}@profiles.invalid',
                   password_hash='!', role='managed', is_active=False,
                   managed_by_id=account.id, profile_name=name)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile_json(profile, own=False)


@router.post('/active')
async def switch_profile(data: ProfileSwitch,
                         context: tuple[Session, User] = Depends(get_auth_context),
                         db: AsyncSession = Depends(get_db)) -> dict:
    session, account = context
    if data.profile_id == account.id:
        session.active_profile_id = None
        active = account
    else:
        active = await db.scalar(select(User).where(
            User.id == data.profile_id, User.managed_by_id == account.id))
        if not active:
            raise HTTPException(404, '档案成员不存在')
        session.active_profile_id = active.id
    await db.commit()
    return {'active': profile_json(active, own=active.id == account.id)}
