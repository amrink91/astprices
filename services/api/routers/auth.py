"""
Авторизация через Telegram Login Widget.
Проверка HMAC-SHA256 (TELEGRAM_BOT_TOKEN), выдача JWT (API_SECRET_KEY).
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
from services.api.deps import get_db, get_current_user

router = APIRouter()
logger = logging.getLogger("api.auth")

JWT_ALGORITHM = settings.jwt_algorithm
JWT_EXPIRE_SECONDS = settings.jwt_expire_hours * 3600


# ── Request / Response schemas ────────────────────────────────

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
    username: Optional[str] = None


class UserMeResponse(BaseModel):
    id: str
    telegram_id: int
    telegram_username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    photo_url: Optional[str] = None
    is_subscribed: bool


# ── Helpers ───────────────────────────────────────────────────

def _verify_telegram_hash(data: TelegramAuthData) -> bool:
    """
    Telegram Login Widget HMAC-SHA256 verification.
    https://core.telegram.org/widgets/login#checking-authorization

    1. Build data_check_string from sorted fields (excluding 'hash').
    2. secret_key = SHA256(TELEGRAM_BOT_TOKEN).
    3. Compare HMAC-SHA256(secret_key, data_check_string) with data.hash.
    """
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not configured")
        return False

    # Reject if auth_date is older than 24 hours
    if time.time() - data.auth_date > 86400:
        return False

    fields: dict[str, str] = {
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
    """Sign JWT with API_SECRET_KEY."""
    now = int(time.time())
    payload = {
        "sub": str(telegram_id),
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, settings.api_secret_key, algorithm=JWT_ALGORITHM)


def _verify_jwt(token: str) -> Optional[dict]:
    """Verify and decode JWT. Returns payload dict or None."""
    try:
        return jwt.decode(token, settings.api_secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/telegram", response_model=TokenResponse)
async def telegram_login(
    data: TelegramAuthData,
    session: AsyncSession = Depends(get_db),
):
    """
    Вход через Telegram Login Widget.
    Проверяет HMAC-SHA256 подпись, создаёт/обновляет пользователя,
    возвращает JWT токен.
    """
    if not _verify_telegram_hash(data):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram signature",
        )

    # Upsert user
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

    from sqlalchemy import func
    user.last_login_at = func.now()
    await session.commit()
    await session.refresh(user)

    logger.info("Login: telegram_id=%s username=%s", data.id, data.username)

    token = _issue_jwt(data.id)
    return TokenResponse(
        access_token=token,
        user_id=str(user.id),
        username=user.telegram_username,
    )


@router.get("/me", response_model=UserMeResponse)
async def me(user=Depends(get_current_user)):
    """Информация о текущем авторизованном пользователе."""
    return UserMeResponse(
        id=str(user.id),
        telegram_id=user.telegram_id,
        telegram_username=user.telegram_username,
        first_name=user.first_name,
        last_name=user.last_name,
        photo_url=user.photo_url,
        is_subscribed=user.is_subscribed,
    )
