"""Telegram Publisher — отправка постов в публичный канал"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from shared.config import settings

logger = logging.getLogger("publisher")


class TelegramPublisher:
    """
    DRY_RUN=true  → посты идут тебе в личку (первые 2 недели)
    DRY_RUN=false → публикуем в @astana_prices_channel
    """

    API = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self) -> None:
        self.token = settings.telegram_bot_token
        self.dry_run = settings.telegram_dry_run
        self.target = settings.telegram_admin_chat_id if self.dry_run else settings.telegram_channel_id

        if self.dry_run:
            logger.warning("🔶 DRY-RUN: посты в личку, не в канал")

    def _url(self, method: str) -> str:
        return self.API.format(token=self.token, method=method)

    async def send_photo_post(
        self,
        image_bytes: bytes,
        caption: str,
        post_type: str,
        product_ids: Optional[list[str]] = None,
        pin: bool = False,
    ) -> Optional[int]:
        """Пост с изображением. Возвращает message_id."""
        caption = caption[:1024]  # Telegram limit для фото

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url("sendPhoto"),
                data={"chat_id": self.target, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("card.png", image_bytes, "image/png")},
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                logger.error(f"Telegram error: {data}")
                return None

            msg_id = data["result"]["message_id"]
            logger.info(f"✅ Опубликован {post_type} msg_id={msg_id}")

            if pin and not self.dry_run:
                await self._pin(msg_id, client)

            await self._save_to_db(post_type, msg_id, caption, product_ids)
            return msg_id

    async def send_text_post(self, text: str, post_type: str) -> Optional[int]:
        """Текстовый пост (аномалии цен)"""
        text = text[:4096]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url("sendMessage"),
                json={"chat_id": self.target, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return None

            msg_id = data["result"]["message_id"]
            await self._save_to_db(post_type, msg_id, text)
            return msg_id

    async def _pin(self, message_id: int, client: httpx.AsyncClient) -> None:
        try:
            await client.post(self._url("pinChatMessage"), json={
                "chat_id": self.target, "message_id": message_id, "disable_notification": True
            })
        except Exception as e:
            logger.warning(f"Не закреплено: {e}")

    async def _save_to_db(self, post_type: str, message_id: int, content: str, product_ids=None) -> None:
        try:
            from shared.db import get_session
            from shared.models import TelegramPost
            async with get_session() as session:
                session.add(TelegramPost(
                    post_type=post_type, message_id=message_id,
                    channel_id=self.target, content_html=content,
                    published_at=datetime.utcnow(),
                ))
                await session.commit()
        except Exception as e:
            logger.warning(f"DB save post: {e}")
