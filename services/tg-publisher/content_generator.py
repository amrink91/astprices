"""
Генератор текстов для Telegram-постов через Gemini Pro.
Строгие правила: нейтральный тон, никаких сравнений «лучший/худший магазин».
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from shared.utils.gemini_client import get_gemini_client

logger = logging.getLogger("content_generator")


@dataclass
class DealItem:
    canonical_name: str
    store_name: str
    price_tenge: Decimal
    old_price_tenge: Optional[Decimal]
    discount_pct: Optional[float]
    store_url: str
    image_url: Optional[str]
    category_emoji: str = "🛒"


@dataclass
class CartTip:
    stores: list[str]
    total_savings: Decimal
    items_count: int
    store_items: dict[str, list[DealItem]]  # store_name → items


class ContentGenerator:
    """Формирует HTML-текст постов для Telegram."""

    def __init__(self) -> None:
        self.gemini = get_gemini_client()

    # ─────────────────────────────────────────────────────────────
    # Публичный API
    # ─────────────────────────────────────────────────────────────

    async def daily_deals_caption(self, deals: list[DealItem]) -> str:
        """Подпись к карточке дневных акций (≤1024 символов)."""
        prompt = self._build_daily_prompt(deals)
        try:
            text = await self.gemini.generate_post_text(prompt)
            return self._trim(text, 1024)
        except Exception as e:
            logger.warning(f"Gemini daily caption: {e}")
            return self._fallback_daily(deals)

    async def weekly_digest_text(self, deals: list[DealItem], week_label: str) -> str:
        """Текст еженедельного дайджеста (≤4096)."""
        prompt = self._build_weekly_prompt(deals, week_label)
        try:
            text = await self.gemini.generate_post_text(prompt)
            return self._trim(text, 4096)
        except Exception as e:
            logger.warning(f"Gemini weekly: {e}")
            return self._fallback_weekly(deals, week_label)

    async def cart_tip_text(self, tip: CartTip) -> str:
        """Текст совета по разделённой корзине (≤4096)."""
        prompt = self._build_cart_prompt(tip)
        try:
            text = await self.gemini.generate_post_text(prompt)
            return self._trim(text, 4096)
        except Exception as e:
            logger.warning(f"Gemini cart tip: {e}")
            return self._fallback_cart(tip)

    async def anomaly_text(self, anomalies: list[dict]) -> str:
        """Текст поста об аномалиях цен (≤4096)."""
        prompt = self._build_anomaly_prompt(anomalies)
        try:
            text = await self.gemini.generate_post_text(prompt)
            return self._trim(text, 4096)
        except Exception as e:
            logger.warning(f"Gemini anomaly: {e}")
            return self._fallback_anomaly(anomalies)

    # ─────────────────────────────────────────────────────────────
    # Промпты
    # ─────────────────────────────────────────────────────────────

    def _build_daily_prompt(self, deals: list[DealItem]) -> str:
        items_text = "\n".join(
            f"- {d.category_emoji} {d.canonical_name}: {d.price_tenge}₸"
            + (f" (было {d.old_price_tenge}₸, скидка {d.discount_pct:.0f}%)" if d.old_price_tenge else "")
            + f" в {d.store_name}"
            for d in deals[:10]
        )
        return f"""Напиши короткий, живой пост для Telegram-канала о ценах на продукты в Астане.
Tone: дружелюбный, информативный. Никаких оценок магазинов. Факты.
Данные акций сегодня:
{items_text}

Формат HTML для Telegram: <b>жирный</b>, <i>курсив</i>, эмодзи ОК.
Длина: 200-400 символов. Завершить: #астана_цены #акции"""

    def _build_weekly_prompt(self, deals: list[DealItem], week_label: str) -> str:
        top = sorted(deals, key=lambda d: d.discount_pct or 0, reverse=True)[:15]
        items_text = "\n".join(
            f"- {d.canonical_name}: {d.price_tenge}₸"
            + (f" −{d.discount_pct:.0f}%" if d.discount_pct else "")
            for d in top
        )
        return f"""Напиши еженедельный дайджест акций на продукты в Астане за {week_label}.
Стиль: журналистский, краткий, нейтральный. Никакой критики магазинов.
Лучшие акции недели:
{items_text}

HTML Telegram формат. Длина 500-900 символов.
В конце: #дайджест #астана_цены"""

    def _build_cart_prompt(self, tip: CartTip) -> str:
        breakdown = "\n".join(
            f"• {store}: {len(items)} товаров"
            for store, items in tip.store_items.items()
        )
        return f"""Напиши практичный совет для Telegram: как выгодно разделить корзину продуктов.
Экономия: {tip.total_savings}₸ на {tip.items_count} товарах.
Разбивка по магазинам:
{breakdown}

Тон: полезный советник, не реклама. Нейтрально. HTML Telegram.
Длина 300-600 символов. #умная_корзина #астана_экономия"""

    def _build_anomaly_prompt(self, anomalies: list[dict]) -> str:
        items_text = "\n".join(
            f"- {a['name']}: {a['direction']} на {abs(a['deviation_pct']):.0f}% → {a['new_price']}₸"
            for a in anomalies[:8]
        )
        return f"""Напиши короткий нейтральный пост об изменениях цен в Астане.
НЕ указывай в каком магазине. Только факт движения цены.
Данные:
{items_text}

HTML Telegram. 150-350 символов. #мониторинг_цен"""

    # ─────────────────────────────────────────────────────────────
    # Fallback-тексты (без Gemini)
    # ─────────────────────────────────────────────────────────────

    def _fallback_daily(self, deals: list[DealItem]) -> str:
        lines = ["🛍 <b>Акции сегодня в Астане</b>\n"]
        for d in deals[:8]:
            line = f"{d.category_emoji} {d.canonical_name} — <b>{d.price_tenge}₸</b>"
            if d.discount_pct:
                line += f" <i>−{d.discount_pct:.0f}%</i>"
            lines.append(line)
        lines.append("\n#астана_цены #акции")
        return "\n".join(lines)

    def _fallback_weekly(self, deals: list[DealItem], week_label: str) -> str:
        lines = [f"📊 <b>Дайджест акций — {week_label}</b>\n"]
        top = sorted(deals, key=lambda d: d.discount_pct or 0, reverse=True)[:12]
        for d in top:
            line = f"• {d.canonical_name} — {d.price_tenge}₸"
            if d.discount_pct:
                line += f" (−{d.discount_pct:.0f}%)"
            lines.append(line)
        lines.append("\n#дайджест #астана_цены")
        return "\n".join(lines)

    def _fallback_cart(self, tip: CartTip) -> str:
        lines = [f"🛒 <b>Выгодная корзина: экономия {tip.total_savings}₸</b>\n"]
        for store, items in tip.store_items.items():
            lines.append(f"<b>{store}</b>: {', '.join(i.canonical_name for i in items[:4])}")
        lines.append(f"\nВсего товаров: {tip.items_count}")
        lines.append("#умная_корзина #астана_экономия")
        return "\n".join(lines)

    def _fallback_anomaly(self, anomalies: list[dict]) -> str:
        lines = ["📈 <b>Изменения цен</b>\n"]
        for a in anomalies[:6]:
            direction = "↑" if a["deviation_pct"] > 0 else "↓"
            lines.append(f"{direction} {a['name']}: {a['new_price']}₸ ({a['deviation_pct']:+.0f}%)")
        lines.append("\n#мониторинг_цен")
        return "\n".join(lines)

    @staticmethod
    def _trim(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        # Обрезаем по последнему пробелу до лимита
        trimmed = text[:limit - 3]
        last_space = trimmed.rfind(" ")
        if last_space > limit * 0.8:
            trimmed = trimmed[:last_space]
        return trimmed + "..."
