"""Celery задачи парсинга — 6 магазинов включая Анвар"""
from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import datetime, timedelta

from services.scheduler.celery_app import app
from shared.config import settings

logger = logging.getLogger("tasks.scrape")

SCRAPERS = {
    "magnum":  "services.scraper.adapters.magnum.MagnumScraper",
    "arbuz":   "services.scraper.adapters.arbuz.ArbuzScraper",
    "small":   "services.scraper.adapters.small.SmallScraper",
    "galmart": "services.scraper.adapters.galmart.GalmartScraper",
    "astore":  "services.scraper.adapters.astore.AStoreScraper",
    "anvar":   "services.scraper.adapters.anvar.AnvarScraper",
}


@app.task(
    bind=True, name="tasks.scrape_store", queue="scrape",
    max_retries=2, default_retry_delay=300,
    soft_time_limit=2400, time_limit=2700,
)
def scrape_store(self, store_slug: str) -> dict:
    return asyncio.run(_scrape_async(store_slug))


async def _scrape_async(store_slug: str) -> dict:
    from shared.db import get_session
    from shared.models import Store, ScrapeRun
    from services.normalizer.normalizer import ProductNormalizer
    from sqlalchemy import select, text

    ScraperClass = _import_scraper(store_slug)
    if not ScraperClass:
        raise ValueError(f"Неизвестный магазин: {store_slug}")

    async with get_session() as session:
        store = (await session.execute(select(Store).where(Store.slug == store_slug))).scalar_one_or_none()
        if not store:
            raise ValueError(f"Магазин '{store_slug}' не найден в БД")

        run = ScrapeRun(store_id=store.id, started_at=datetime.utcnow(), status="running")
        session.add(run)
        await session.commit()
        logger.info(f"[{store_slug}] Старт парсинга run_id={run.id}")

        scraper = ScraperClass()
        normalizer = ProductNormalizer(session)
        batch = []
        scraped = 0
        BATCH = 50

        try:
            async for product in scraper.scrape_all_products():
                batch.append(product)
                scraped += 1
                if len(batch) >= BATCH:
                    await normalizer.normalize_batch(batch)
                    logger.info(f"[{store_slug}] {scraped} товаров обработано")
                    batch.clear()

            if batch:
                await normalizer.normalize_batch(batch)

            # Обновляем materialized view
            await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices"))
            await session.commit()

            run.status = "success"
            run.finished_at = datetime.utcnow()
            run.products_scraped = scraped
            store.scrape_health_score = min(1.0, store.scrape_health_score + 0.1)
            await session.commit()
            logger.info(f"[{store_slug}] ✅ Готово: {scraped} товаров")

        except Exception as e:
            run.status = "failed"
            run.finished_at = datetime.utcnow()
            run.products_scraped = scraped
            run.error_message = str(e)
            store.scrape_health_score = max(0.0, store.scrape_health_score - 0.3)
            await session.commit()
            logger.error(f"[{store_slug}] ❌ Ошибка: {e}")

            if store.scrape_health_score <= 0.4:
                await _alert_admin(
                    f"⚠️ <b>Парсер {store.display_name} нестабилен!</b>\n"
                    f"Health score: {store.scrape_health_score:.1f}\n"
                    f"Ошибка: {str(e)[:300]}"
                )
            raise
        finally:
            await scraper.close()

    return {"store": store_slug, "scraped": scraped, "status": run.status}


@app.task(name="tasks.refresh_materialized_view")
def refresh_materialized_view() -> None:
    asyncio.run(_refresh_view())


async def _refresh_view() -> None:
    from shared.db import get_session
    from sqlalchemy import text
    async with get_session() as session:
        await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY current_prices"))
        await session.commit()
    logger.info("Materialized view обновлён")


@app.task(name="tasks.detect_anomalies")
def detect_anomalies() -> dict:
    return asyncio.run(_detect_anomalies())


async def _detect_anomalies() -> dict:
    from shared.db import get_session
    from shared.models import PriceAnomaly, StoreProduct
    from sqlalchemy import text

    async with get_session() as session:
        # Ищем резкие изменения за последние 2 часа
        rows = (await session.execute(text("""
            WITH latest AS (
                SELECT
                    sp.id AS sp_id,
                    sp.price_tenge AS current_price,
                    AVG(ph.price_tenge) OVER (
                        PARTITION BY sp.id
                        ORDER BY ph.recorded_at
                        ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
                    ) AS avg_30,
                    ROW_NUMBER() OVER (PARTITION BY sp.id ORDER BY ph.recorded_at DESC) AS rn
                FROM store_products sp
                JOIN price_history ph ON ph.store_product_id = sp.id
                WHERE ph.recorded_at >= NOW() - INTERVAL '2 hours'
            )
            SELECT sp_id, current_price, avg_30,
                   (current_price - avg_30) / avg_30 * 100 AS deviation_pct
            FROM latest
            WHERE rn = 1 AND avg_30 > 0
              AND ABS((current_price - avg_30) / avg_30) > 0.3
            LIMIT 50
        """))).fetchall()

        added = 0
        for row in rows:
            anomaly_type = "spike" if row.deviation_pct > 0 else "drop"
            anomaly = PriceAnomaly(
                store_product_id=row.sp_id,
                anomaly_type=anomaly_type,
                old_price=row.avg_30,
                new_price=row.current_price,
                deviation_pct=round(row.deviation_pct, 1),
            )
            session.add(anomaly)
            added += 1

        await session.commit()

    logger.info(f"Аномалии: найдено {added} новых")
    return {"anomalies_found": added}


@app.task(name="tasks.check_scraper_health")
def check_scraper_health() -> dict:
    return asyncio.run(_check_health())


async def _check_health() -> dict:
    from shared.db import get_session
    from shared.models import Store, ScrapeRun
    from sqlalchemy import select, desc

    threshold = datetime.utcnow() - timedelta(hours=8)
    issues = []

    async with get_session() as session:
        stores = (await session.execute(select(Store).where(Store.is_active == True))).scalars().all()
        for store in stores:
            last = (await session.execute(
                select(ScrapeRun)
                .where(ScrapeRun.store_id == store.id, ScrapeRun.status == "success")
                .order_by(desc(ScrapeRun.finished_at)).limit(1)
            )).scalar_one_or_none()

            if not last or last.finished_at < threshold:
                issues.append({"store": store.slug, "last": last.finished_at.isoformat() if last else "никогда"})

    if issues:
        msg = "🔴 Устаревшие данные:\n" + "\n".join(f"  • {i['store']}: {i['last']}" for i in issues)
        await _alert_admin(msg)

    return {"issues": issues}


async def _alert_admin(message: str) -> None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": settings.telegram_admin_chat_id, "text": message, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.error(f"Алерт не отправлен: {e}")


def _import_scraper(slug: str):
    path = SCRAPERS.get(slug)
    if not path:
        return None
    mod_path, cls_name = path.rsplit(".", 1)
    return getattr(importlib.import_module(mod_path), cls_name)
