"""
Генератор контента для Telegram-постов через Gemini Pro.
Все тексты на русском, нейтральный тон, без критики магазинов, только факты.
"""
from __future__ import annotations

import logging
from typing import Any

from shared.utils.gemini_client import get_gemini_client

logger = logging.getLogger("content_generator")

MAX_PHOTO_CAPTION = 1024   # Telegram limit for photo captions
MAX_TEXT_MESSAGE = 4096    # Telegram limit for text messages


def _truncate(text: str, limit: int = MAX_PHOTO_CAPTION) -> str:
    """Обрезка текста до лимита, сохраняя целостность строк."""
    text = text.strip()
    if len(text) <= limit:
        return text
    trimmed = text[: limit - 3]
    last_nl = trimmed.rfind("\n")
    if last_nl > limit * 0.7:
        trimmed = trimmed[:last_nl]
    return trimmed + "..."


# ─────────────────────────────────────────────────────────────────────
# 1. Топ скидки дня
# ─────────────────────────────────────────────────────────────────────

async def generate_daily_deals_post(deals: list[dict[str, Any]]) -> str:
    """
    Генерирует пост «Топ скидки дня» (caption для фото, <= 1024 символов).

    Каждый deal:
        canonical_name, price_tenge, old_price_tenge, discount_pct,
        store_name, store_url, store_image_url,
        other_stores: [{store_name, price_tenge, store_url}]
    """
    if not deals:
        return ""

    # Формируем блок данных для каждого товара
    items_block = ""
    for i, d in enumerate(deals, 1):
        store_url = d.get("store_url") or ""
        store_link = (
            f'<a href="{store_url}">{d["store_name"]}</a>'
            if store_url else d["store_name"]
        )
        items_block += (
            f"{i}. <b>{d['canonical_name']}</b>\n"
            f"   {int(d['old_price_tenge'])}₸ -> <b>{int(d['price_tenge'])}₸</b> "
            f"(-{d['discount_pct']:.0f}%) | {store_link}\n"
        )
        # Другие магазины с ценами и ссылками
        for s in d.get("other_stores", []):
            s_url = s.get("store_url") or ""
            s_link = (
                f'<a href="{s_url}">{s["store_name"]}</a>'
                if s_url else s["store_name"]
            )
            items_block += f"   {s_link} — {int(s['price_tenge'])}₸\n"
        items_block += "\n"

    # Генерируем заголовок через Gemini
    prompt = (
        "Напиши ОДИН короткий заголовок (макс 60 символов) для Telegram поста "
        "о топ-5 скидках дня на продукты в Астане. "
        "Один эмодзи в начале. Дружелюбный, информативный тон. "
        "Верни ТОЛЬКО заголовок, одна строка, без кавычек."
    )

    client = get_gemini_client()
    try:
        title = await client.generate_post_text(prompt)
        title = title.strip().split("\n")[0][:80]
    except Exception as e:
        logger.warning(f"Gemini title fallback: {e}")
        title = "🏷 Лучшие скидки дня в Астане"

    caption = f"{title}\n\n{items_block}#астана_цены #акции"
    return _truncate(caption, MAX_PHOTO_CAPTION)


# ─────────────────────────────────────────────────────────────────────
# 2. Еженедельный дайджест
# ─────────────────────────────────────────────────────────────────────

async def generate_weekly_digest_post(stats: dict[str, Any]) -> str:
    """
    Генерирует еженедельный дайджест цен (caption для фото, <= 1024 символов).

    stats:
        period, total_products_tracked, avg_basket_change_pct,
        top_drops: [{canonical_name, drop_pct, old_price, new_price, store_name, store_url}],
        top_rises: [{canonical_name, rise_pct, old_price, new_price, store_name, store_url}],
        cheapest_stores: [{store_name, products_cheapest}]
    """
    drops_text = _format_price_changes(stats.get("top_drops", []), "drop")
    rises_text = _format_price_changes(stats.get("top_rises", []), "rise")
    stores_text = _format_cheapest_stores(stats.get("cheapest_stores", []))

    prompt = f"""Напиши информативный Telegram пост — еженедельный дайджест цен в Астане.

Период: {stats.get('period', 'прошлая неделя')}
Отслеживаем: {stats.get('total_products_tracked', 0)} товаров
Средняя корзина: {stats.get('avg_basket_change_pct', 0):+.1f}%

Снижения цен:
{drops_text}

Повышения цен:
{rises_text}

Магазины с самыми низкими ценами:
{stores_text}

ПРАВИЛА:
- Русский, для жителей Астаны
- Нейтральный тон, только факты, НЕ критикуй магазины
- HTML разметка: <b>, <i>, <a href="">
- Макс 850 символов
- Один эмодзи в заголовке
- В конце: #дайджест #астана_цены"""

    client = get_gemini_client()
    try:
        text = await client.generate_post_text(prompt)
    except Exception as e:
        logger.warning(f"Gemini weekly digest fallback: {e}")
        text = _fallback_weekly_digest(stats)

    return _truncate(text, MAX_PHOTO_CAPTION)


# ─────────────────────────────────────────────────────────────────────
# 3. Умная корзина
# ─────────────────────────────────────────────────────────────────────

async def generate_cart_tip_post(optimization: dict[str, Any]) -> str:
    """
    Генерирует пост-рекомендацию по оптимизации корзины (caption для фото, <= 1024).

    optimization:
        category_name, strategy, grand_total, baseline_total, savings, savings_pct,
        assignments: [{store_name, items: [{canonical_name, price, store_url}],
                       subtotal, delivery_cost, total}]
    """
    assignments_text = ""
    for a in optimization.get("assignments", []):
        items_lines = "\n".join(
            f"   - {it['canonical_name']} — {int(it['price'])}₸"
            for it in a.get("items", [])[:5]
        )
        remaining = len(a.get("items", [])) - 5
        if remaining > 0:
            items_lines += f"\n   +ещё {remaining} товаров"
        assignments_text += (
            f"\n{a['store_name']}: {int(a['total'])}₸ "
            f"(товары {int(a['subtotal'])}₸ + доставка {int(a['delivery_cost'])}₸)\n"
            f"{items_lines}\n"
        )

    prompt = f"""Напиши короткий Telegram пост — совет по оптимизации корзины продуктов в Астане.

Категория: {optimization.get('category_name', 'Продукты')}
Стратегия: {optimization.get('strategy', 'split')}
Оптимальная сумма: {int(optimization.get('grand_total', 0))}₸
В одном магазине было бы: {int(optimization.get('baseline_total', 0))}₸
Экономия: {int(optimization.get('savings', 0))}₸ ({optimization.get('savings_pct', 0):.1f}%)

По магазинам:
{assignments_text}

ПРАВИЛА:
- Русский, для жителей Астаны
- Нейтральный информационный стиль, НЕ критикуй магазины
- HTML: <b>, <i>
- Макс 850 символов, акцент на экономии
- Один эмодзи в заголовке
- В конце: #умная_корзина #астана_экономия"""

    client = get_gemini_client()
    try:
        text = await client.generate_post_text(prompt)
    except Exception as e:
        logger.warning(f"Gemini cart tip fallback: {e}")
        text = _fallback_cart_tip(optimization)

    return _truncate(text, MAX_PHOTO_CAPTION)


# ─────────────────────────────────────────────────────────────────────
# 4. Аномалия цены
# ─────────────────────────────────────────────────────────────────────

async def generate_anomaly_post(anomaly: dict[str, Any]) -> str:
    """
    Генерирует пост об аномалии цены (текстовый пост, <= 4096 символов).

    anomaly:
        canonical_name, store_name, old_price, new_price, deviation_pct,
        anomaly_type, gemini_explanation, store_url, avg_market_price
    """
    deviation = anomaly.get("deviation_pct", 0)
    direction = "выросла" if deviation > 0 else "упала"
    abs_pct = abs(deviation)
    emoji = "📈" if deviation > 0 else "📉"

    # Получаем объяснение через Gemini если его ещё нет
    explanation = anomaly.get("gemini_explanation") or ""
    if not explanation:
        client = get_gemini_client()
        try:
            explanation = await client.explain_anomaly(
                product_name=anomaly["canonical_name"],
                store_name=anomaly["store_name"],
                old_price=float(anomaly["old_price"]),
                new_price=float(anomaly["new_price"]),
                avg_market_price=float(
                    anomaly.get("avg_market_price", anomaly["old_price"])
                ),
            )
        except Exception as e:
            logger.warning(f"Gemini anomaly explanation fallback: {e}")
            explanation = ""

    # Ссылка на магазин
    store_url = anomaly.get("store_url", "")
    store_link = (
        f'<a href="{store_url}">{anomaly["store_name"]}</a>'
        if store_url else anomaly["store_name"]
    )

    text = (
        f'{emoji} <b>Цена {direction} на {abs_pct:.0f}%</b>\n\n'
        f'<b>{anomaly["canonical_name"]}</b>\n'
        f'{store_link}: {int(anomaly["old_price"])}₸ -> '
        f'<b>{int(anomaly["new_price"])}₸</b>\n'
    )

    avg = anomaly.get("avg_market_price")
    if avg:
        text += f'Средняя по рынку: {int(avg)}₸\n'

    if explanation:
        text += f'\n{explanation.strip()}'

    text += "\n\n#мониторинг_цен #астана_цены"

    return _truncate(text, MAX_TEXT_MESSAGE)


# ─────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────

def _format_price_changes(items: list[dict], direction: str) -> str:
    """Форматирование списка изменений цен для промпта Gemini."""
    lines = []
    for it in items[:5]:
        key = "drop_pct" if direction == "drop" else "rise_pct"
        pct = it.get(key, 0)
        sign = "-" if direction == "drop" else "+"
        store_name = it.get("store_name", "")
        lines.append(
            f"- {it['canonical_name']}: {int(it['old_price'])}₸ -> {int(it['new_price'])}₸ "
            f"({sign}{abs(pct):.0f}%) — {store_name}"
        )
    return "\n".join(lines) if lines else "нет данных"


def _format_cheapest_stores(stores: list[dict]) -> str:
    """Форматирование списка самых дешёвых магазинов для промпта."""
    lines = []
    for s in stores[:5]:
        lines.append(
            f"- {s['store_name']}: самая низкая цена у {s['products_cheapest']} товаров"
        )
    return "\n".join(lines) if lines else "нет данных"


def _fallback_weekly_digest(stats: dict) -> str:
    """Текст если Gemini недоступен."""
    change = stats.get("avg_basket_change_pct", 0)
    word = "снизилась" if change < 0 else "выросла"
    drops = stats.get("top_drops", [])
    drops_text = ""
    for d in drops[:3]:
        drops_text += (
            f"\n- {d['canonical_name']}: "
            f"{int(d['old_price'])}₸ -> {int(d['new_price'])}₸ "
            f"(-{abs(d.get('drop_pct', 0)):.0f}%)"
        )
    return (
        f"📊 <b>Еженедельный дайджест цен — Астана</b>\n\n"
        f"Период: {stats.get('period', 'прошлая неделя')}\n"
        f"Отслеживаем: {stats.get('total_products_tracked', 0)} товаров\n"
        f"Средняя корзина {word} на {abs(change):.1f}%\n"
        f"\n<b>Лучшие снижения:</b>{drops_text}\n"
        f"\n#дайджест #астана_цены"
    )


def _fallback_cart_tip(optimization: dict) -> str:
    """Текст если Gemini недоступен."""
    assignments = optimization.get("assignments", [])
    stores_text = ""
    for a in assignments:
        items_count = len(a.get("items", []))
        stores_text += f"\n- {a['store_name']}: {items_count} товаров на {int(a['total'])}₸"

    return (
        f"🛒 <b>Совет: как сэкономить на продуктах</b>\n\n"
        f"Категория: {optimization.get('category_name', 'Продукты')}\n"
        f"Экономия: <b>{int(optimization.get('savings', 0))}₸</b> "
        f"({optimization.get('savings_pct', 0):.1f}%)\n"
        f"Итого: {int(optimization.get('grand_total', 0))}₸ "
        f"вместо {int(optimization.get('baseline_total', 0))}₸\n"
        f"\n<b>Разбивка:</b>{stores_text}\n"
        f"\n#умная_корзина #астана_экономия"
    )
