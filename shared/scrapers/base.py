"""Базовый класс парсера — все магазины наследуют отсюда"""
from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from typing import AsyncIterator, Optional

import httpx
from pytz import timezone

from shared.config import settings

ASTANA_TZ = timezone("Asia/Almaty")
logger = logging.getLogger(__name__)


@dataclass
class RawProduct:
    """Сырой товар — до нормализации Gemini"""
    store_slug: str
    store_sku: str
    name_raw: str
    price_tenge: Decimal
    store_url: str

    old_price_tenge: Optional[Decimal] = None
    in_stock: bool = True
    is_promoted: bool = False
    promo_label: Optional[str] = None
    store_image_url: Optional[str] = None
    category_path: list[str] = field(default_factory=list)
    unit: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    raw_json: dict = field(default_factory=dict)


class AbstractStoreScraper(ABC):
    """
    Базовый класс. Статический IP → увеличенные задержки, имитация человека.
    """

    def __init__(self, store_slug: str) -> None:
        self.store_slug = store_slug
        self.logger = logging.getLogger(f"scraper.{store_slug}")
        self._request_count = 0
        self._client = httpx.AsyncClient(
            timeout=settings.scraper_timeout_seconds,
            headers=self._build_headers(),
            follow_redirects=True,
        )

    def _build_headers(self) -> dict:
        return {
            "User-Agent": settings.random_user_agent,
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "ru-KZ,ru;q=0.9,kk;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
        }

    def _is_active_hours(self) -> bool:
        """Парсим только 07:00-23:00 Астана — имитируем рабочего человека"""
        now = datetime.now(ASTANA_TZ).time()
        return time(settings.scraper_active_hours_start, 0) <= now <= time(settings.scraper_active_hours_end, 0)

    async def _human_delay(self, extra_ms: int = 0) -> None:
        """Случайная задержка + редкие длинные паузы как у человека"""
        delay = settings.random_delay_ms + extra_ms

        # Каждые ~20 запросов — долгая пауза (отвлёкся)
        if self._request_count > 0 and self._request_count % 20 == 0:
            delay += random.randint(5000, 15000)

        await asyncio.sleep(delay / 1000)
        self._request_count += 1

        # Обновляем User-Agent каждые 50 запросов
        if self._request_count % 50 == 0:
            self._client.headers["User-Agent"] = settings.random_user_agent

    async def _get_json(self, url: str, params: dict = None, **kwargs) -> dict:
        """GET с retry, задержкой и обработкой 429/403"""
        await self._human_delay()

        for attempt in range(settings.scraper_max_retries):
            try:
                resp = await self._client.get(url, params=params, **kwargs)

                if resp.status_code == 429:
                    wait = 60 * (attempt + 1)
                    self.logger.warning(f"Rate limit 429. Пауза {wait}с...")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code == 403:
                    raise PermissionError(f"403 Forbidden: {url}. Проверь IP или cookies.")

                resp.raise_for_status()
                return resp.json()

            except httpx.TimeoutException:
                self.logger.warning(f"Timeout {url}, попытка {attempt + 1}")
                await asyncio.sleep(5 * (attempt + 1))
            except httpx.HTTPStatusError as e:
                self.logger.error(f"HTTP {e.response.status_code}: {url}")
                if attempt == settings.scraper_max_retries - 1:
                    raise
                await asyncio.sleep(10 * (attempt + 1))

        raise Exception(f"Исчерпаны {settings.scraper_max_retries} попытки: {url}")

    async def _post_json(self, url: str, json_data: dict, **kwargs) -> dict:
        """POST с retry"""
        await self._human_delay()

        for attempt in range(settings.scraper_max_retries):
            try:
                resp = await self._client.post(url, json=json_data, **kwargs)
                if resp.status_code == 429:
                    await asyncio.sleep(60 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                self.logger.warning(f"POST error {url}: {e}")
                await asyncio.sleep(10 * (attempt + 1))

        raise Exception(f"POST failed: {url}")

    @staticmethod
    def parse_price(text: str) -> Optional[Decimal]:
        """Парсинг цены: '1 299 ₸', '1299.50', '1,299тг' → Decimal"""
        if not text:
            return None
        cleaned = ""
        for ch in str(text):
            if ch.isdigit():
                cleaned += ch
            elif ch in ".,":
                cleaned += "."
        cleaned = cleaned.rstrip(".")
        try:
            return Decimal(cleaned) if cleaned else None
        except Exception:
            return None

    @abstractmethod
    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        """Основной метод — реализуется в каждом адаптере"""
        ...

    async def close(self) -> None:
        await self._client.aclose()
