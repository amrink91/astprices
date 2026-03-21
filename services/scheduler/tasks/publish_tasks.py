"""
Celery задачи публикации постов в Telegram.
daily_deals, weekly_digest, cart_tip, publish_anomalies
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from services.scheduler.celery_app import app

logger = logging.getLogger("tasks.publish")


# ─────────────────────────────────────────────────────────────
# daily_deals  — каждый день в 12:00 AST (07:00 UTC)
# ─────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_daily_deals", queue="publish")
def publish_daily_deals() -> dict:
    return asyncio.run(_daily_deals())


async def _daily_deals() -> dict:
    from shared.db import get_session
    from sqlalchemy import text
    from services.tg_publisher.content_generator import ContentGenerator, DealItem
    from services.tg_publisher.image_generator import DealRow, generate_deals_card
    from services.tg_publisher.publisher import TelegramPublisher

    async with get_session() as session:
        rows = (await session.execute(text("""
            SELECT
                p.canonical_name,
                s.display_name  AS store_name,
                cp.price_tenge,
                cp.old_price_tenge,
                cp.discount_pct,
                cp.store_url,
                cp.store_image_url,
                COALESCE(c.icon_emoji, '🛒') AS emoji
            FROM current_prices cp
            JOIN products p      ON p.id = cp.product_id
            JOIN stores s        ON s.id = cp.store_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE cp.is_promoted = true
              AND cp.discount_pct >= 10
            ORDER BY cp.discount_pct DESC NULLS LAST
            LIMIT 6
        """))).fetchall()

    if not rows:
        logger.info("daily_deals: нет акций для публикации")
        return {"published": False, "reason": "no_deals"}

    deals_gen = [
        DealItem(
            canonical_name=r.canonical_name,
            store_name=r.store_name,
            price_tenge=r.price_tenge,
            old_price_tenge=r.old_price_tenge,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            store_url=r.store_url,
            image_url=r.store_image_url,
            category_emoji=r.emoji,
        )
        for r in rows
    ]

    deals_img = [
        DealRow(
            emoji=r.emoji,
            name=r.canonical_name,
            price=r.price_tenge,
            old_price=r.old_price_tenge,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            store=r.store_name,
        )
        for r in rows
    ]

    gen = ContentGenerator()
    today_str = datetime.utcnow().strftime("%d.%m.%Y")
    caption = await gen.daily_deals_caption(deals_gen)

    image_bytes = generate_deals_card(
        deals_img,
        title=f"🔥 Акции дня — {today_str}",
    )

    pub = TelegramPublisher()
    product_ids = []   # TODO: добавить product_ids если нужно
    msg_id = await pub.send_photo_post(
        image_bytes=image_bytes,
        caption=caption,
        post_type="daily_deals",
        product_ids=product_ids,
        pin=False,
    )

    logger.info(f"daily_deals: опубликован msg_id={msg_id}")
    return {"published": True, "msg_id": msg_id, "deals_count": len(rows)}


# ─────────────────────────────────────────────────────────────
# weekly_digest — понедельник в 09:00 AST (04:00 UTC)
# ─────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_weekly_digest", queue="publish")
def publish_weekly_digest() -> dict:
    return asyncio.run(_weekly_digest())


async def _weekly_digest() -> dict:
    from shared.db import get_session
    from sqlalchemy import text
    from services.tg_publisher.content_generator import ContentGenerator, DealItem
    from services.tg_publisher.image_generator import DealRow, generate_weekly_card
    from services.tg_publisher.publisher import TelegramPublisher

    week_start = datetime.utcnow() - timedelta(days=7)
    week_label = (
        f"{week_start.strftime('%d.%m')} — {datetime.utcnow().strftime('%d.%m.%Y')}"
    )

    async with get_session() as session:
        # Лучшие скидки за неделю (из истории)
        rows = (await session.execute(text("""
            SELECT
                p.canonical_name,
                s.display_name  AS store_name,
                MIN(ph.price_tenge) AS min_price,
                MAX(ph.old_price_tenge) AS max_old,
                CASE
                    WHEN MAX(ph.old_price_tenge) > 0
                    THEN ROUND((MAX(ph.old_price_tenge) - MIN(ph.price_tenge))
                          / MAX(ph.old_price_tenge) * 100, 1)
                END AS discount_pct,
                COALESCE(c.icon_emoji, '🛒') AS emoji
            FROM price_history ph
            JOIN store_products sp  ON sp.id = ph.store_product_id
            JOIN products p         ON p.id = sp.product_id
            JOIN stores s           ON s.id = sp.store_id
            LEFT JOIN categories c  ON c.id = p.category_id
            WHERE ph.recorded_at >= :week_start
              AND ph.is_promoted = true
              AND ph.old_price_tenge IS NOT NULL
            GROUP BY p.canonical_name, s.display_name, c.icon_emoji
            HAVING MAX(ph.old_price_tenge) > MIN(ph.price_tenge)
            ORDER BY discount_pct DESC NULLS LAST
            LIMIT 10
        """), {"week_start": week_start})).fetchall()

    if not rows:
        logger.info("weekly_digest: нет данных")
        return {"published": False, "reason": "no_data"}

    deals_gen = [
        DealItem(
            canonical_name=r.canonical_name,
            store_name=r.store_name,
            price_tenge=r.min_price,
            old_price_tenge=r.max_old,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            store_url="",
            image_url=None,
            category_emoji=r.emoji,
        )
        for r in rows
    ]

    deals_img = [
        DealRow(
            emoji=r.emoji,
            name=r.canonical_name,
            price=r.min_price,
            old_price=r.max_old,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            store=r.store_name,
        )
        for r in rows
    ]

    gen = ContentGenerator()
    caption = await gen.weekly_digest_text(deals_gen, week_label)
    image_bytes = generate_weekly_card(deals_img, week_label)

    pub = TelegramPublisher()
    msg_id = await pub.send_photo_post(
        image_bytes=image_bytes,
        caption=caption,
        post_type="weekly_digest",
        pin=True,
    )

    logger.info(f"weekly_digest: опубликован msg_id={msg_id}")
    return {"published": True, "msg_id": msg_id}


# ─────────────────────────────────────────────────────────────
# cart_tip — вт/чт/сб в 10:00 AST (05:00 UTC)
# ─────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_cart_tip", queue="publish")
def publish_cart_tip() -> dict:
    return asyncio.run(_cart_tip())


async def _cart_tip() -> dict:
    from shared.db import get_session
    from services.optimizer.optimizer import SplitCartOptimizer
    from services.tg_publisher.content_generator import ContentGenerator, CartTip, DealItem
    from services.tg_publisher.image_generator import CartStore, generate_cart_card
    from services.tg_publisher.publisher import TelegramPublisher

    # Базовая корзина: молоко, хлеб, яйца, масло, гречка + популярные
    BASKET_CATEGORIES = [
        "молоко", "хлеб", "яйцо", "масло сливочное",
        "греча", "рис", "сахар", "куриное филе",
    ]

    async with get_session() as session:
        opt = SplitCartOptimizer(session)
        result = await opt.get_best_split_for_categories(BASKET_CATEGORIES)

    if not result or result.total_savings < 100:
        logger.info("cart_tip: экономия незначительна, пропускаем")
        return {"published": False, "reason": "low_savings"}

    stores_content = []
    store_items_map: dict = {}
    for store_name, items in result.store_assignments.items():
        subtotal = sum(i["price"] for i in items)
        delivery = result.delivery_costs.get(store_name, Decimal("0"))
        stores_content.append(CartStore(
            name=store_name,
            items=[i["name"] for i in items],
            subtotal=subtotal,
            delivery=delivery,
        ))
        from services.tg_publisher.content_generator import DealItem
        store_items_map[store_name] = [
            DealItem(
                canonical_name=i["name"],
                store_name=store_name,
                price_tenge=i["price"],
                old_price_tenge=None,
                discount_pct=None,
                store_url="",
                image_url=None,
            )
            for i in items
        ]

    tip = CartTip(
        stores=list(result.store_assignments.keys()),
        total_savings=result.total_savings,
        items_count=sum(len(v) for v in result.store_assignments.values()),
        store_items=store_items_map,
    )

    gen = ContentGenerator()
    caption = await gen.cart_tip_text(tip)

    image_bytes = generate_cart_card(
        stores=stores_content,
        total_savings=result.total_savings,
        total_sum=result.total_cost,
    )

    pub = TelegramPublisher()
    msg_id = await pub.send_photo_post(
        image_bytes=image_bytes,
        caption=caption,
        post_type="cart_tip",
    )

    logger.info(f"cart_tip: опубликован msg_id={msg_id}, экономия={result.total_savings}₸")
    return {"published": True, "msg_id": msg_id, "savings": str(result.total_savings)}


# ─────────────────────────────────────────────────────────────
# publish_anomalies — каждые 20 минут (только если есть новые)
# ─────────────────────────────────────────────────────────────

@app.task(name="tasks.publish_anomalies", queue="publish")
def publish_anomalies() -> dict:
    return asyncio.run(_publish_anomalies())


async def _publish_anomalies() -> dict:
    from shared.db import get_session
    from shared.models import PriceAnomaly, StoreProduct, Product
    from sqlalchemy import select, update
    from sqlalchemy.orm import joinedload
    from services.tg_publisher.content_generator import ContentGenerator
    from services.tg_publisher.image_generator import AnomalyRow, generate_anomaly_card
    from services.tg_publisher.publisher import TelegramPublisher
    from shared.utils.gemini_client import get_gemini_client

    async with get_session() as session:
        anomalies = (await session.execute(
            select(PriceAnomaly)
            .options(
                joinedload(PriceAnomaly.store_product)
                .joinedload(StoreProduct.product)
            )
            .where(PriceAnomaly.published == False)  # noqa: E712
            .order_by(PriceAnomaly.detected_at.desc())
            .limit(8)
        )).scalars().unique().all()

        if not anomalies:
            return {"published": False, "reason": "no_anomalies"}

        # Загружаем объяснения через Gemini
        gemini = get_gemini_client()
        for a in anomalies:
            if not a.gemini_explanation:
                try:
                    a.gemini_explanation = await gemini.explain_anomaly(
                        name=a.store_product.product.canonical_name if a.store_product else "товар",
                        old_price=float(a.old_price),
                        new_price=float(a.new_price),
                        deviation_pct=float(a.deviation_pct),
                    )
                except Exception:
                    pass

        await session.commit()

        anomaly_dicts = [
            {
                "name": (a.store_product.product.canonical_name
                         if a.store_product and a.store_product.product else "Товар"),
                "direction": "рост" if a.deviation_pct > 0 else "снижение",
                "deviation_pct": float(a.deviation_pct),
                "new_price": float(a.new_price),
                "old_price": float(a.old_price),
                "emoji": "📈" if a.deviation_pct > 0 else "📉",
            }
            for a in anomalies
        ]

        gen = ContentGenerator()
        text = await gen.anomaly_text(anomaly_dicts)

        anomaly_rows = [
            AnomalyRow(
                name=d["name"],
                category_emoji=d["emoji"],
                old_price=Decimal(str(d["old_price"])),
                new_price=Decimal(str(d["new_price"])),
                deviation_pct=d["deviation_pct"],
            )
            for d in anomaly_dicts
        ]
        image_bytes = generate_anomaly_card(anomaly_rows)

        pub = TelegramPublisher()
        msg_id = await pub.send_photo_post(
            image_bytes=image_bytes,
            caption=text,
            post_type="anomaly",
        )

        if msg_id:
            # Отмечаем опубликованными
            ids = [a.id for a in anomalies]
            await session.execute(
                update(PriceAnomaly)
                .where(PriceAnomaly.id.in_(ids))
                .values(published=True)
            )
            await session.commit()

    logger.info(f"publish_anomalies: {len(anomalies)} аномалий, msg_id={msg_id}")
    return {"published": True, "msg_id": msg_id, "count": len(anomalies)}
