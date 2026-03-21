"""
Авторизация через Telegram Login Widget.
Проверка HMAC-SHA256, выдача JWT.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import logging
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.models import User
from services.api.deps import get_db

router = APIRouter()
logger = logging.getLogger("api.auth")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 30 * 24 * 3600   # 30 дней


# ── Схемы ──────────────────────────────────────────────────────

class TelegramAuthData(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: Optional[str]


# ── Helpers ────────────────────────────────────────────────────

def _verify_telegram_hash(data: TelegramAuthData) -> bool:
    """
    Telegram Login Widget HMAC-SHA256 verification.
    https://core.telegram.org/widgets/login#checking-authorization
    """
    # Проверяем свежесть: не старше 24 часов
    if time.time() - data.auth_date > 86400:
        return False

    # data_check_string = ключи в алфавитном порядке, кроме hash
    fields = {
        "auth_date": str(data.auth_date),
        "first_name": data.first_name,
        "id": str(data.id),
    }
    if data.last_name:
        fields["last_name"] = data.last_name
    if data.username:
        fields["username"] = data.username
    if data.photo_url:
        fields["photo_url"] = data.photo_url

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))

    secret_key = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, data.hash)


def _issue_jwt(telegram_id: int) -> str:
    payload = {
        "sub": str(telegram_id),
        "exp": int(time.time()) + JWT_EXPIRE_SECONDS,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, settings.api_secret_key, algorithm=JWT_ALGORITHM)


def _verify_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.api_secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ── Endpoints ──────────────────────────────────────────────────

@router.post("/telegram", response_model=TokenResponse)
async def telegram_login(
    data: TelegramAuthData,
    session: AsyncSession = Depends(get_db),
):
    """Вход через Telegram Login Widget."""
    if not _verify_telegram_hash(data):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверная подпись Telegram",
        )

    # Upsert пользователя
    user = (await session.execute(
        select(User).where(User.telegram_id == data.id)
    )).scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=data.id,
            telegram_username=data.username,
            first_name=data.first_name,
            last_name=data.last_name,
            photo_url=data.photo_url,
        )
        session.add(user)
    else:
        user.telegram_username = data.username
        user.first_name = data.first_name
        if data.last_name:
            user.last_name = data.last_name
        if data.photo_url:
            user.photo_url = data.photo_url

    await session.commit()
    logger.info(f"Вход: telegram_id={data.id} username={data.username}")

    token = _issue_jwt(data.id)
    return TokenResponse(
        access_token=token,
        user_id=str(user.id),
        username=user.telegram_username,
    )


@router.get("/me")
async def me(
    session: AsyncSession = Depends(get_db),
    credentials=None,
):
    """Информация о текущем пользователе."""
    from fastapi import Request
    from fastapi.security import HTTPBearer
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
