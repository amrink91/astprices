"""Зависимости FastAPI: сессия БД, текущий пользователь."""
from __future__ import annotations

from typing import AsyncIterator, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.db import get_session
from sqlalchemy.ext.asyncio import AsyncSession

bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    session: AsyncSession = Depends(get_db),
):
    """Возвращает пользователя если токен передан, иначе None."""
    if not credentials:
        return None
    from services.api.routers.auth import _verify_jwt
    from shared.models import User
    from sqlalchemy import select

    payload = _verify_jwt(credentials.credentials)
    if not payload:
        return None
    telegram_id = payload.get("sub")
    if not telegram_id:
        return None
    user = (await session.execute(
        select(User).where(User.telegram_id == int(telegram_id))
    )).scalar_one_or_none()
    return user


async def get_current_user(
    user=Depends(get_current_user_optional),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация через Telegram",
        )
    return user
