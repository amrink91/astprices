from datetime import datetime
from typing import Optional
from sqlalchemy import ARRAY, Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, UUIDMixin


class TelegramPost(Base, UUIDMixin):
    __tablename__ = "telegram_posts"

    # weekly_digest | daily_deals | price_alert | cart_tip | anomaly
    post_type:    Mapped[str]           = mapped_column(String(50),  nullable=False, index=True)
    message_id:   Mapped[Optional[int]] = mapped_column(Integer,     nullable=True)
    channel_id:   Mapped[str]           = mapped_column(String(100), nullable=False)
    content_html: Mapped[str]           = mapped_column(Text,        nullable=False)
    image_path:   Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_pinned:    Mapped[bool]          = mapped_column(Boolean, default=False)
    product_ids:  Mapped[Optional[list]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=True)
