"""
Celery задачи публикации постов в Telegram.
Используют реальные изображения товаров из магазинов (store_image_url).
НЕ генерируют изображения через Pillow.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import httpx

from services.scheduler.celery_app import app

logger = logging.getLogger("tasks.publish")


# ─────────────────────────────────────────────────────────────────────
# Утилита: скачать изображение товара из магазина
# ─────────────────────────────────────────────────────────────────────

async def _download_image(url: str, timeout: int = 15) -> Optional[bytes]:
    """Скачивает изображение по URL. Возвращает bytes или None."""
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type and not url.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                logger.warning(f"Не изображение: {content_type} для {url}")
                return None
            return resp.content
    except Exception as e:
        logger.warning(f"Не удалось скачать изображение {url}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────
# 1. daily_deals — каждый день в 12:00 AST (07:00 UTC)
# ─────────────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_daily_deals", queue="publish")
def publish_daily_deals() -> dict:
    return asyncio.run(_daily_deals())


async def _daily_deals() -> dict:
    from shared.db import get_session
    from sqlalchemy import text
    from services.tg_publisher.content_generator import generate_daily_deals_post
    from services.tg_publisher.publisher import TelegramPublisher

    async with get_session() as session:
        # Топ-5 товаров с наибольшей скидкой сегодня.
        # Для каждого товара — самый дешёвый вариант (с изображением).
        rows = (await session.execute(text("""
            WITH ranked AS (
                SELECT
                    p.id           AS product_id,
                    p.canonical_name,
                    s.display_name AS store_name,
                    s.slug         AS store_slug,
                    cp.price_tenge,
                    cp.old_price_tenge,
                    cp.discount_pct,
                    cp.store_url,
                    cp.store_image_url,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.id ORDER BY cp.price_tenge ASC
                    ) AS rn
                FROM current_prices cp
                JOIN products p ON p.id = cp.product_id
                JOIN stores s   ON s.id = cp.store_id
                WHERE cp.is_promoted = true
                  AND cp.discount_pct >= 10
                  AND cp.in_stock = true
                  AND cp.store_image_url IS NOT NULL
            )
            SELECT *
            FROM ranked
            WHERE rn = 1
            ORDER BY discount_pct DESC NULLS LAST
            LIMIT 5
        """))).fetchall()

    if not rows:
        logger.info("daily_deals: нет акций для публикации")
        return {"published": False, "reason": "no_deals"}

    product_ids = [r.product_id for r in rows]

    # Собираем цены из других магазинов для каждого товара
    async with get_session() as session:
        other_rows = (await session.execute(text("""
            SELECT
                cp.product_id,
                s.display_name AS store_name,
                cp.price_tenge,
                cp.store_url
            FROM current_prices cp
            JOIN stores s ON s.id = cp.store_id
            WHERE cp.product_id = ANY(:ids)
              AND cp.in_stock = true
            ORDER BY cp.product_id, cp.price_tenge ASC
        """), {"ids": product_ids})).fetchall()

    # Группируем другие магазины по product_id
    other_by_product: dict = {}
    for r in other_rows:
        other_by_product.setdefault(r.product_id, []).append({
            "store_name": r.store_name,
            "price_tenge": float(r.price_tenge),
            "store_url": r.store_url or "",
        })

    # Формируем данные для content_generator
    cheapest_row = rows[0]  # самый большой дисконт — он будет с фото
    deals = []
    for r in rows:
        # Другие магазины (исключаем тот, что уже самый дешёвый)
        others = [
            s for s in other_by_product.get(r.product_id, [])
            if s["store_name"] != r.store_name
        ][:3]  # макс 3 других магазина

        deals.append({
            "canonical_name": r.canonical_name,
            "price_tenge": float(r.price_tenge),
            "old_price_tenge": float(r.old_price_tenge) if r.old_price_tenge else float(r.price_tenge),
            "discount_pct": float(r.discount_pct) if r.discount_pct else 0,
            "store_name": r.store_name,
            "store_url": r.store_url or "",
            "store_image_url": r.store_image_url or "",
            "other_stores": others,
        })

    # Генерируем текст поста
    caption = await generate_daily_deals_post(deals)

    # Скачиваем реальное изображение товара из магазина (самый дешёвый с
    # наибольшей скидкой)
    image_bytes = await _download_image(cheapest_row.store_image_url)

    if not image_bytes:
        # Пробуем другие товары
        for r in rows[1:]:
            image_bytes = await _download_image(r.store_image_url)
            if image_bytes:
                break

    if not image_bytes:
        # Отправляем как текстовый пост
        pub = TelegramPublisher()
        msg_id = await pub.send_text_post(text=caption, post_type="daily_deals")
        logger.info(f"daily_deals: текстовый пост msg_id={msg_id}")
        return {"published": True, "msg_id": msg_id, "deals_count": len(rows), "mode": "text"}

    pub = TelegramPublisher()
    msg_id = await pub.send_photo_post(
        image_bytes=image_bytes,
        caption=caption,
        post_type="daily_deals",
        product_ids=[str(r.product_id) for r in rows],
        pin=False,
    )

    logger.info(f"daily_deals: опубликован msg_id={msg_id}")
    return {"published": True, "msg_id": msg_id, "deals_count": len(rows)}


# ─────────────────────────────────────────────────────────────────────
# 2. weekly_digest — понедельник 09:00 AST (04:00 UTC)
# ─────────────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_weekly_digest", queue="publish")
def publish_weekly_digest() -> dict:
    return asyncio.run(_weekly_digest())


async def _weekly_digest() -> dict:
    from shared.db import get_session
    from sqlalchemy import text
    from services.tg_publisher.content_generator import generate_weekly_digest_post
    from services.tg_publisher.publisher import TelegramPublisher

    week_start = datetime.utcnow() - timedelta(days=7)
    week_label = (
        f"{week_start.strftime('%d.%m')} — {datetime.utcnow().strftime('%d.%m.%Y')}"
    )

    async with get_session() as session:
        # Топ снижений цен за неделю
        drops = (await session.execute(text("""
            SELECT
                p.canonical_name,
                s.display_name AS store_name,
                MAX(ph.old_price_tenge)  AS old_price,
                MIN(ph.price_tenge)      AS new_price,
                ROUND(
                    (MAX(ph.old_price_tenge) - MIN(ph.price_tenge))
                    / MAX(ph.old_price_tenge) * 100, 1
                ) AS drop_pct,
                (array_agg(sp.store_url ORDER BY ph.price_tenge ASC))[1] AS store_url,
                (array_agg(sp.store_image_url ORDER BY ph.price_tenge ASC))[1] AS store_image_url
            FROM price_history ph
            JOIN store_products sp ON sp.id = ph.store_product_id
            JOIN products p        ON p.id = sp.product_id
            JOIN stores s          ON s.id = sp.store_id
            WHERE ph.recorded_at >= :week_start
              AND ph.old_price_tenge IS NOT NULL
              AND ph.old_price_tenge > ph.price_tenge
            GROUP BY p.canonical_name, s.display_name
            HAVING MAX(ph.old_price_tenge) > MIN(ph.price_tenge)
            ORDER BY drop_pct DESC NULLS LAST
            LIMIT 5
        """), {"week_start": week_start})).fetchall()

        # Топ повышений цен за неделю
        rises = (await session.execute(text("""
            SELECT
                p.canonical_name,
                s.display_name AS store_name,
                MIN(ph.price_tenge)       AS old_price,
                MAX(ph.price_tenge)       AS new_price,
                ROUND(
                    (MAX(ph.price_tenge) - MIN(ph.price_tenge))
                    / MIN(ph.price_tenge) * 100, 1
                ) AS rise_pct
            FROM price_history ph
            JOIN store_products sp ON sp.id = ph.store_product_id
            JOIN products p        ON p.id = sp.product_id
            JOIN stores s          ON s.id = sp.store_id
            WHERE ph.recorded_at >= :week_start
              AND ph.old_price_tenge IS NOT NULL
            GROUP BY p.canonical_name, s.display_name
            HAVING MAX(ph.price_tenge) > MIN(ph.price_tenge)
            ORDER BY rise_pct DESC NULLS LAST
            LIMIT 5
        """), {"week_start": week_start})).fetchall()

        # Магазины с самыми низкими ценами
        cheapest = (await session.execute(text("""
            SELECT
                s.display_name AS store_name,
                COUNT(*) AS products_cheapest
            FROM current_prices cp
            JOIN stores s ON s.id = cp.store_id
            WHERE cp.in_stock = true
              AND cp.price_tenge = (
                  SELECT MIN(cp2.price_tenge)
                  FROM current_prices cp2
                  WHERE cp2.product_id = cp.product_id
                    AND cp2.in_stock = true
              )
            GROUP BY s.display_name
            ORDER BY products_cheapest DESC
            LIMIT 5
        """))).fetchall()

        # Общее количество отслеживаемых товаров
        total_products = (await session.execute(text(
            "SELECT COUNT(DISTINCT product_id) FROM current_prices WHERE in_stock = true"
        ))).scalar() or 0

        # Среднее изменение цены за неделю
        avg_change = (await session.execute(text("""
            SELECT AVG(change_pct) FROM (
                SELECT
                    (MAX(ph.price_tenge) - MIN(ph.price_tenge))
                    / NULLIF(MIN(ph.price_tenge), 0) * 100 AS change_pct
                FROM price_history ph
                WHERE ph.recorded_at >= :week_start
                GROUP BY ph.store_product_id
                HAVING MIN(ph.price_tenge) > 0
            ) sub
        """), {"week_start": week_start})).scalar() or 0

    if not drops and not rises:
        logger.info("weekly_digest: нет данных за неделю")
        return {"published": False, "reason": "no_data"}

    stats = {
        "period": week_label,
        "total_products_tracked": total_products,
        "avg_basket_change_pct": float(avg_change),
        "top_drops": [
            {
                "canonical_name": r.canonical_name,
                "drop_pct": float(r.drop_pct) if r.drop_pct else 0,
                "old_price": float(r.old_price),
                "new_price": float(r.new_price),
                "store_name": r.store_name,
                "store_url": getattr(r, "store_url", "") or "",
            }
            for r in drops
        ],
        "top_rises": [
            {
                "canonical_name": r.canonical_name,
                "rise_pct": float(r.rise_pct) if r.rise_pct else 0,
                "old_price": float(r.old_price),
                "new_price": float(r.new_price),
                "store_name": r.store_name,
            }
            for r in rises
        ],
        "cheapest_stores": [
            {
                "store_name": r.store_name,
                "products_cheapest": r.products_cheapest,
            }
            for r in cheapest
        ],
    }

    caption = await generate_weekly_digest_post(stats)

    # Используем изображение товара с наибольшей скидкой
    image_bytes = None
    for r in drops:
        img_url = getattr(r, "store_image_url", None)
        if img_url:
            image_bytes = await _download_image(img_url)
            if image_bytes:
                break

    pub = TelegramPublisher()
    if image_bytes:
        msg_id = await pub.send_photo_post(
            image_bytes=image_bytes,
            caption=caption,
            post_type="weekly_digest",
            pin=True,
        )
    else:
        msg_id = await pub.send_text_post(text=caption, post_type="weekly_digest")

    logger.info(f"weekly_digest: опубликован msg_id={msg_id}")
    return {"published": True, "msg_id": msg_id}


# ─────────────────────────────────────────────────────────────────────
# 3. cart_tip — вт/чт/сб 10:00 AST (05:00 UTC)
# ─────────────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_cart_tip", queue="publish")
def publish_cart_tip() -> dict:
    return asyncio.run(_cart_tip())


async def _cart_tip() -> dict:
    from shared.db import get_session
    from sqlalchemy import text as sa_text
    from services.optimizer.optimizer import SplitCartOptimizer
    from services.tg_publisher.content_generator import generate_cart_tip_post
    from services.tg_publisher.publisher import TelegramPublisher

    # Выбираем популярную категорию с ротацией по дню недели
    ALL_CATEGORIES = [
        ["dairy", "bakery", "grocery"],
        ["meat", "vegetables", "oils"],
        ["drinks", "frozen", "snacks"],
    ]
    day_index = datetime.utcnow().timetuple().tm_yday % len(ALL_CATEGORIES)
    category_slugs = ALL_CATEGORIES[day_index]

    async with get_session() as session:
        optimizer = SplitCartOptimizer(session)
        result = await optimizer.get_best_split_for_categories(category_slugs)

    if not result or result.savings < Decimal("100"):
        logger.info("cart_tip: экономия < 100₸, пропускаем")
        return {"published": False, "reason": "low_savings"}

    # Формируем данные для генератора контента
    assignments_data = []
    first_image_url: Optional[str] = None

    for assignment in result.assignments:
        items_data = []
        for item in assignment.items:
            items_data.append({
                "canonical_name": item.canonical_name,
                "price": float(item.unit_price * item.quantity),
                "store_url": item.store_url or "",
            })
            # Запоминаем первое доступное изображение
            if not first_image_url and item.image_url:
                first_image_url = item.image_url

        assignments_data.append({
            "store_name": assignment.store_name,
            "items": items_data,
            "subtotal": float(assignment.items_subtotal),
            "delivery_cost": float(assignment.delivery_cost),
            "total": float(assignment.total),
        })

    # Получаем название категории
    async with get_session() as session:
        cat_name_row = (await session.execute(sa_text(
            "SELECT name_ru FROM categories WHERE slug = ANY(:slugs) LIMIT 1"
        ), {"slugs": category_slugs})).first()
    category_name = cat_name_row.name_ru if cat_name_row else "Продукты"

    optimization_data = {
        "category_name": category_name,
        "strategy": result.strategy,
        "grand_total": float(result.grand_total),
        "baseline_total": float(result.baseline_single_store_total),
        "savings": float(result.savings),
        "savings_pct": result.savings_pct,
        "assignments": assignments_data,
    }

    caption = await generate_cart_tip_post(optimization_data)

    # Скачиваем изображение товара
    image_bytes = await _download_image(first_image_url) if first_image_url else None

    pub = TelegramPublisher()
    if image_bytes:
        msg_id = await pub.send_photo_post(
            image_bytes=image_bytes,
            caption=caption,
            post_type="cart_tip",
        )
    else:
        msg_id = await pub.send_text_post(text=caption, post_type="cart_tip")

    logger.info(f"cart_tip: опубликован msg_id={msg_id}, экономия={result.savings}₸")
    return {"published": True, "msg_id": msg_id, "savings": str(result.savings)}


# ─────────────────────────────────────────────────────────────────────
# 4. publish_anomalies — каждые 20 минут
# ─────────────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_anomalies", queue="publish")
def publish_anomalies() -> dict:
    return asyncio.run(_publish_anomalies())


async def _publish_anomalies() -> dict:
    from shared.db import get_session
    from shared.models import PriceAnomaly, StoreProduct, Product, Store
    from sqlalchemy import select, update, text as sa_text
    from sqlalchemy.orm import joinedload
    from services.tg_publisher.content_generator import generate_anomaly_post
    from services.tg_publisher.publisher import TelegramPublisher

    async with get_session() as session:
        # Загружаем неопубликованные аномалии с продуктами и магазинами
        anomalies = (await session.execute(
            select(PriceAnomaly)
            .options(
                joinedload(PriceAnomaly.store_product)
                .joinedload(StoreProduct.product),
                joinedload(PriceAnomaly.store_product)
                .joinedload(StoreProduct.store),
            )
            .where(PriceAnomaly.published == False)  # noqa: E712
            .order_by(PriceAnomaly.detected_at.desc())
            .limit(5)
        )).scalars().unique().all()

        if not anomalies:
            return {"published": False, "reason": "no_anomalies"}

        published_count = 0

        for anomaly in anomalies:
            sp = anomaly.store_product
            if not sp or not sp.product:
                continue

            product = sp.product
            store = sp.store

            # Средняя цена по рынку для этого товара
            avg_row = (await session.execute(sa_text("""
                SELECT AVG(price_tenge) AS avg_price
                FROM current_prices
                WHERE product_id = :pid AND in_stock = true
            """), {"pid": product.id})).first()
            avg_market = float(avg_row.avg_price) if avg_row and avg_row.avg_price else None

            # Генерируем объяснение через Gemini если ещё нет
            if not anomaly.gemini_explanation:
                from shared.utils.gemini_client import get_gemini_client
                gemini = get_gemini_client()
                try:
                    anomaly.gemini_explanation = await gemini.explain_anomaly(
                        product_name=product.canonical_name,
                        store_name=store.display_name,
                        old_price=float(anomaly.old_price),
                        new_price=float(anomaly.new_price),
                        avg_market_price=avg_market or float(anomaly.old_price),
                    )
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Gemini anomaly explain: {e}")

            anomaly_data = {
                "canonical_name": product.canonical_name,
                "store_name": store.display_name,
                "old_price": float(anomaly.old_price) if anomaly.old_price else 0,
                "new_price": float(anomaly.new_price),
                "deviation_pct": float(anomaly.deviation_pct),
                "anomaly_type": anomaly.anomaly_type,
                "gemini_explanation": anomaly.gemini_explanation or "",
                "store_url": sp.store_url or "",
                "avg_market_price": avg_market,
            }

            text = await generate_anomaly_post(anomaly_data)

            # Аномалии отправляем как текстовый пост (без изображения).
            # Если есть изображение товара — отправляем с фото.
            pub = TelegramPublisher()
            image_bytes = await _download_image(sp.store_image_url)

            if image_bytes:
                msg_id = await pub.send_photo_post(
                    image_bytes=image_bytes,
                    caption=text[:1024],
                    post_type="anomaly",
                )
            else:
                msg_id = await pub.send_text_post(text=text, post_type="anomaly")

            if msg_id:
                anomaly.published = True
                anomaly.published_at = datetime.utcnow()
                published_count += 1

        await session.commit()

    logger.info(f"publish_anomalies: опубликовано {published_count} из {len(anomalies)}")
    return {"published": published_count > 0, "count": published_count}
