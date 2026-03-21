"""
Gemini API клиент с ротацией 2 аккаунтов и rate limiting.
Бесплатный тир: Flash 15 RPM, Pro 2 RPM (на аккаунт).
С 2 аккаунтами: Flash 30 RPM, Pro 4 RPM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import google.generativeai as genai

from shared.config import settings

logger = logging.getLogger(__name__)


class GeminiModel(Enum):
    FLASH = "flash"   # нормализация товаров
    PRO = "pro"       # генерация текстов постов
    EMBED = "embed"   # эмбеддинги


@dataclass
class AccountState:
    api_key: str
    flash_rpm: int = 0
    flash_rpd: int = 0
    pro_rpm: int = 0
    pro_rpd: int = 0
    minute_start: float = field(default_factory=time.time)
    day_start: float = field(default_factory=time.time)
    is_healthy: bool = True

    def _reset_if_needed(self) -> None:
        now = time.time()
        if now - self.minute_start >= 60:
            self.flash_rpm = 0
            self.pro_rpm = 0
            self.minute_start = now
        if now - self.day_start >= 86400:
            self.flash_rpd = 0
            self.pro_rpd = 0
            self.day_start = now

    def can_flash(self) -> bool:
        self._reset_if_needed()
        return (
            self.is_healthy
            and self.flash_rpm < settings.gemini_flash_rpm_limit
            and self.flash_rpd < settings.gemini_flash_rpd_limit
        )

    def can_pro(self) -> bool:
        self._reset_if_needed()
        return (
            self.is_healthy
            and self.pro_rpm < settings.gemini_pro_rpm_limit
            and self.pro_rpd < settings.gemini_pro_rpd_limit
        )


class GeminiClient:
    """
    Ротация 2 аккаунтов Gemini.
    Автоматически выбирает аккаунт с доступным лимитом.
    """

    def __init__(self) -> None:
        self._accounts = [AccountState(api_key=k) for k in settings.gemini_keys]
        self._lock = asyncio.Lock()

        if not self._accounts:
            raise ValueError("Нет Gemini ключей в .env (GEMINI_API_KEY_1/2)")

        logger.info(f"Gemini: {len(self._accounts)} аккаунт(а), "
                    f"Flash {settings.gemini_flash_rpm_total} RPM total")

    def _pick(self, model_type: GeminiModel) -> Optional[AccountState]:
        for acc in self._accounts:
            if model_type in (GeminiModel.FLASH, GeminiModel.EMBED):
                if acc.can_flash():
                    return acc
            elif model_type == GeminiModel.PRO:
                if acc.can_pro():
                    return acc
        return None

    async def _wait_for(self, model_type: GeminiModel, timeout: float = 120) -> AccountState:
        start = time.time()
        while time.time() - start < timeout:
            acc = self._pick(model_type)
            if acc:
                return acc
            logger.warning(f"Gemini лимит исчерпан ({model_type.value}), ждём 10с...")
            await asyncio.sleep(10)
        raise TimeoutError(f"Gemini лимит не освободился за {timeout}с")

    async def normalize_products(self, products_batch: list[dict]) -> list[dict]:
        """
        Нормализация батча товаров через Gemini Flash.
        До 30 товаров за 1 запрос.
        """
        async with self._lock:
            acc = await self._wait_for(GeminiModel.FLASH)
            acc.flash_rpm += 1
            acc.flash_rpd += 1

        genai.configure(api_key=acc.api_key)
        model = genai.GenerativeModel(settings.gemini_model_normalize)

        prompt = f"""Ты — система нормализации продуктов питания для казахстанского рынка (Астана).

Верни JSON массив. Для каждого товара:
- "id": тот же id что во входных данных
- "canonical_name": "Категория Бренд характеристика объём" (пример: "Молоко Простоквашино 3.2% 1л")
- "category_slug": dairy|meat|fish|grocery|vegetables|drinks|frozen|snacks|bakery|oils|household|baby|other
- "subcategory": уточнение (например "кефир" для dairy)
- "brand": бренд/производитель
- "unit": kg|l|pcs|g|ml
- "unit_size": число (1.0 для 1кг, 0.5 для 500мл)
- "confidence": 0.0-1.0

ВАЖНО: одинаковые товары из разных магазинов → одинаковый canonical_name.
Верни ТОЛЬКО JSON, без комментариев.

{json.dumps(products_batch, ensure_ascii=False)}"""

        try:
            resp = await model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )
            return json.loads(resp.text)
        except Exception as e:
            acc.is_healthy = False
            logger.error(f"Gemini normalize error: {e}")
            raise

    async def generate_post_text(self, prompt: str) -> str:
        """Генерация текста поста через Gemini Pro"""
        async with self._lock:
            acc = await self._wait_for(GeminiModel.PRO)
            acc.pro_rpm += 1
            acc.pro_rpd += 1

        genai.configure(api_key=acc.api_key)
        model = genai.GenerativeModel(settings.gemini_model_generate)

        safety_prefix = """ПРАВИЛА (обязательно):
1. Нейтральный информационный стиль — только факты
2. ЗАПРЕЩЕНО: критиковать магазины, слова "жадный"/"завышают"/"обманывают"
3. РАЗРЕШЕНО: "самая низкая цена в X", "цена выросла на Y%", "акция до Z"
4. Пиши на русском, для жителей Астаны, макс. 1200 символов

"""
        try:
            resp = await model.generate_content_async(
                safety_prefix + prompt,
                generation_config=genai.GenerationConfig(temperature=0.7, max_output_tokens=1500),
            )
            return resp.text
        except Exception as e:
            acc.is_healthy = False
            logger.error(f"Gemini generate error: {e}")
            raise

    async def get_embedding(self, text: str) -> list[float]:
        """768-мерный эмбеддинг для семантического поиска"""
        async with self._lock:
            acc = await self._wait_for(GeminiModel.EMBED)
            acc.flash_rpm += 1
            acc.flash_rpd += 1

        genai.configure(api_key=acc.api_key)
        try:
            result = genai.embed_content(
                model=settings.gemini_embedding_model,
                content=text,
                task_type="RETRIEVAL_DOCUMENT",
            )
            return result["embedding"]
        except Exception as e:
            logger.error(f"Gemini embedding error: {e}")
            raise

    async def explain_anomaly(
        self, product_name: str, store_name: str,
        old_price: float, new_price: float, avg_market_price: float,
    ) -> str:
        """Объяснение аномалии цены в 1-2 предложения"""
        change_pct = (new_price - old_price) / old_price * 100
        direction = "выросла" if change_pct > 0 else "упала"

        prompt = f"""Напиши КОРОТКОЕ (1-2 предложения) объяснение изменения цены для Telegram поста.

Продукт: {product_name}
Магазин: {store_name}
Цена {direction}: {old_price:.0f}₸ → {new_price:.0f}₸ ({change_pct:+.1f}%)
Средняя по рынку: {avg_market_price:.0f}₸

Предположи причину (сезонность, курс, логистика, акция). НЕ обвиняй магазин."""

        return await self.generate_post_text(prompt)


_client: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
