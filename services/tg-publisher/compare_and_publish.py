"""
Сравнение цен между магазинами и публикация в Telegram.
Запуск: python -m services.tg-publisher.compare_and_publish
Или через Celery Beat каждые 15 минут.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from decimal import Decimal

import httpx
from sqlalchemy import text

from shared.config import settings
from shared.db import get_session

logger = logging.getLogger("compare_publish")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-30s %(levelname)-8s  %(message)s")

# Названия магазинов для отображения
STORE_NAMES = {
    "magnum": "Magnum",
    "arbuz": "Arbuz",
    "galmart": "Galmart",
    "small": "Small",
}

# Эмодзи для категорий
CATEGORY_EMOJI = {
    "Молоко": "🥛", "Сыр": "🧀", "Яйца": "🥚", "Хлеб": "🍞",
    "Мясо": "🥩", "Рыба": "🐟", "Кофе": "☕", "Чай": "🍵",
    "Сок": "🧃", "Вода": "💧", "Масло": "🫒", "Крупа": "🌾",
    "Макарон": "🍝", "Соус": "🥫", "Приправ": "🧂", "Шоколад": "🍫",
    "Печенье": "🍪", "Йогурт": "🥛", "Творог": "🧀", "Сметан": "🥛",
    "Колбас": "🌭", "Сосис": "🌭", "Детск": "👶", "Каша": "🥣",
}


def get_emoji(name: str) -> str:
    """Подбираем эмодзи по названию продукта."""
    name_lower = name.lower()
    for keyword, emoji in CATEGORY_EMOJI.items():
        if keyword.lower() in name_lower:
            return emoji
    return "🛒"


async def get_price_comparisons() -> list[dict]:
    """
    Получаем продукты, доступные в 2+ магазинах, с разницей в ценах.
    """
    query = text("""
        SELECT
            p.id as product_id,
            p.canonical_name,
            s.slug as store_slug,
            sp.price_tenge,
            sp.old_price_tenge,
            sp.store_url,
            sp.is_promoted
        FROM store_products sp
        JOIN products p ON sp.product_id = p.id
        JOIN stores s ON sp.store_id = s.id
        WHERE sp.product_id IS NOT NULL
          AND p.canonical_name IS NOT NULL
          AND sp.price_tenge > 0
          AND sp.in_stock = true
        ORDER BY p.id, sp.price_tenge ASC
    """)

    async with get_session() as session:
        result = await session.execute(query)
        rows = result.fetchall()

    # Группируем по product_id, берём только лучшую цену каждого магазина
    products = {}
    for row in rows:
        pid = row.product_id
        if pid not in products:
            products[pid] = {
                "product_id": pid,
                "canonical_name": row.canonical_name,
                "stores": {},
            }
        slug = row.store_slug
        price = float(row.price_tenge)
        # Берём самую низкую цену для каждого магазина
        if slug not in products[pid]["stores"] or price < products[pid]["stores"][slug]["price"]:
            products[pid]["stores"][slug] = {
                "slug": slug,
                "name": STORE_NAMES.get(slug, slug),
                "price": price,
                "old_price": float(row.old_price_tenge) if row.old_price_tenge else None,
                "url": row.store_url or "",
                "is_promoted": row.is_promoted,
            }

    # Фильтруем: только продукты в 2+ РАЗНЫХ магазинах с разницей в цене
    comparisons = []
    for p in products.values():
        stores = list(p["stores"].values())
        if len(stores) < 2:
            continue
        # Сортируем по цене
        stores.sort(key=lambda x: x["price"])
        cheapest = stores[0]["price"]
        most_expensive = stores[-1]["price"]
        if most_expensive <= cheapest or cheapest <= 0:
            continue

        saving = most_expensive - cheapest
        saving_pct = (saving / most_expensive) * 100

        # Пропускаем аномально большие разницы (>80%) — скорее всего ошибка нормализации
        if saving_pct > 80:
            continue

        comparisons.append({
            "canonical_name": p["canonical_name"],
            "stores": stores,
            "cheapest_price": cheapest,
            "max_price": most_expensive,
            "saving": saving,
            "saving_pct": saving_pct,
        })

    # Сортируем по экономии в %
    comparisons.sort(key=lambda x: x["saving_pct"], reverse=True)
    return comparisons


def format_product_post(comp: dict) -> str:
    """
    Формат одного продукта:
    ☕ Кофе Jacobs Monarch растворимый 400г
    ✅ Magnum — 8 889₸ (акция, было 12 099₸)
    ❌ Arbuz — 12 099₸
    💰 Экономия: 3 210₸ (27%)
    """
    emoji = get_emoji(comp["canonical_name"])
    lines = [f"{emoji} <b>{comp['canonical_name']}</b>"]

    cheapest_slug = comp["stores"][0]["slug"]

    for store in comp["stores"]:
        is_cheapest = store["slug"] == cheapest_slug
        icon = "✅" if is_cheapest else "❌"
        price_str = f"{int(store['price']):,}₸".replace(",", " ")

        # Ссылка на магазин
        if store["url"]:
            store_link = f'<a href="{store["url"]}">{store["name"]} — {price_str}</a>'
        else:
            store_link = f'{store["name"]} — {price_str}'

        # Акция
        promo_text = ""
        if store.get("is_promoted") and store.get("old_price"):
            old_str = f"{int(store['old_price']):,}₸".replace(",", " ")
            promo_text = f" (акция, было {old_str})"

        lines.append(f"{icon} {store_link}{promo_text}")

    saving_str = f"{int(comp['saving']):,}₸".replace(",", " ")
    lines.append(f"💰 Экономия: {saving_str} ({comp['saving_pct']:.0f}%)")

    return "\n".join(lines)


def build_telegram_post(comparisons: list[dict], batch_num: int = 1) -> str:
    """Собираем полный пост для Telegram (до 4096 символов)."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    header = f"🔍 <b>Сравнение цен — Астана</b>\n📅 {now}\n\n"

    body = ""
    count = 0
    for comp in comparisons:
        product_text = format_product_post(comp)
        # Проверяем лимит Telegram (4096 символов)
        if len(header + body + product_text + "\n\n") > 3900:
            break
        body += product_text + "\n\n"
        count += 1

    footer = (
        f"📊 Показано {count} из {len(comparisons)} совпадений\n"
        f"🏪 Магазины: Magnum, Arbuz, Galmart, Small\n\n"
        f"#сравнение_цен #астана #корзина_астаны"
    )

    return header + body + footer


async def send_to_telegram(text: str) -> bool:
    """Отправляем пост в Telegram."""
    token = settings.telegram_bot_token
    dry_run = settings.telegram_dry_run
    target = settings.telegram_admin_chat_id if dry_run else settings.telegram_channel_id

    if dry_run:
        logger.info(f"DRY-RUN: отправляю в {target} (не в канал)")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()

        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            logger.info(f"Пост отправлен! msg_id={msg_id}")
            return True
        else:
            logger.error(f"Ошибка Telegram: {data}")
            return False


async def main():
    logger.info("Запуск сравнения цен...")

    comparisons = await get_price_comparisons()
    logger.info(f"Найдено {len(comparisons)} совпадений между магазинами")

    if not comparisons:
        logger.warning("Нет совпадений для сравнения!")
        return

    # Первый пост — топ по экономии в %
    post_text = build_telegram_post(comparisons)
    logger.info(f"Пост: {len(post_text)} символов")
    print(post_text)
    print("---")

    await send_to_telegram(post_text)


if __name__ == "__main__":
    asyncio.run(main())
