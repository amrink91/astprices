from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """Авторизация через Telegram Login Widget"""
    __tablename__ = "users"

    telegram_id:       Mapped[int]           = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name:        Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name:         Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    photo_url:         Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    last_login_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_subscribed:     Mapped[bool]          = mapped_column(Boolean, default=True)
    preferences:       Mapped[dict]          = mapped_column(JSONB,   default=dict)
