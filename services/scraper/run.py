"""Scraper entry point — запускается из docker, слушает Redis Stream."""
import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from shared.config import settings
from shared.db import get_session

logging.basicConfig(level=settings.log_level, format="%(asctime)s  %(name)-25s %(levelname)-8s  %(message)s")
logger = logging.getLogger("scraper")

STORE_SLUG = os.environ.get("STORE_SLUG", "magnum")

SCRAPERS = {
    "magnum": "services.scraper.adapters.magnum.MagnumScraper",
    "arbuz": "services.scraper.adapters.arbuz.ArbuzScraper",
    "small": "services.scraper.adapters.small.SmallScraper",
    "galmart": "services.scraper.adapters.galmart.GalmartScraper",
    "astore": "services.scraper.adapters.astore.AStoreScraper",
    "anvar": "services.scraper.adapters.anvar.AnvarScraper",
}


def _import_scraper(dotpath: str):
    module_path, cls_name = dotpath.rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


async def main():
    logger.info(f"Scraper [{STORE_SLUG}] starting, waiting for commands via Redis Stream...")

    r = aioredis.from_url(settings.redis_url)
    stream_key = f"scrape:{STORE_SLUG}"

    # Create consumer group if not exists
    try:
        await r.xgroup_create(stream_key, "scrapers", id="0", mkstream=True)
    except Exception:
        pass

    scraper_cls = _import_scraper(SCRAPERS[STORE_SLUG])

    while True:
        try:
            messages = await r.xreadgroup(
                "scrapers", f"worker-{STORE_SLUG}",
                {stream_key: ">"},
                count=1, block=30000
            )

            if messages:
                for stream, entries in messages:
                    for msg_id, data in entries:
                        logger.info(f"Received scrape command: {data}")
                        scraper = scraper_cls()
                        try:
                            products = []
                            async for p in scraper.scrape_all_products():
                                products.append(p)

                            logger.info(f"Scraped {len(products)} products from {STORE_SLUG}")

                            # Push to normalizer stream
                            for batch_start in range(0, len(products), 50):
                                batch = products[batch_start:batch_start + 50]
                                batch_data = json.dumps(
                                    [p.__dict__ for p in batch],
                                    default=str, ensure_ascii=False
                                )
                                await r.xadd("normalize:queue", {"store": STORE_SLUG, "products": batch_data})
                        finally:
                            await scraper.close()

                        await r.xack(stream_key, "scrapers", msg_id)
            else:
                # No messages, just idle
                pass

        except Exception as e:
            logger.error(f"Scraper error: {e}", exc_info=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
