"""Normalizer entry point — слушает Redis Stream normalize:queue."""
import asyncio
import json
import logging

import redis.asyncio as aioredis

from shared.config import settings
from shared.db import get_session
from shared.scrapers.base import RawProduct
from services.normalizer.normalizer import ProductNormalizer

logging.basicConfig(level=settings.log_level, format="%(asctime)s  %(name)-25s %(levelname)-8s  %(message)s")
logger = logging.getLogger("normalizer")


async def main():
    logger.info("Normalizer starting, listening on normalize:queue...")

    r = aioredis.from_url(settings.redis_url)
    stream_key = "normalize:queue"

    try:
        await r.xgroup_create(stream_key, "normalizers", id="0", mkstream=True)
    except Exception:
        pass

    while True:
        try:
            messages = await r.xreadgroup(
                "normalizers", "worker-1",
                {stream_key: ">"},
                count=1, block=30000
            )

            if messages:
                for stream, entries in messages:
                    for msg_id, data in entries:
                        store = data.get(b"store", data.get("store", b"unknown"))
                        if isinstance(store, bytes):
                            store = store.decode()
                        products_raw = data.get(b"products", data.get("products", b"[]"))
                        if isinstance(products_raw, bytes):
                            products_raw = products_raw.decode()

                        products_data = json.loads(products_raw)
                        logger.info(f"Normalizing {len(products_data)} products from {store}")

                        raw_products = []
                        for p in products_data:
                            try:
                                raw_products.append(RawProduct(**p))
                            except Exception as e:
                                logger.warning(f"Skip bad product: {e}")

                        if raw_products:
                            async with get_session() as session:
                                normalizer = ProductNormalizer(session)
                                await normalizer.normalize_batch(raw_products)
                                await session.commit()

                        await r.xack(stream_key, "normalizers", msg_id)

        except Exception as e:
            logger.error(f"Normalizer error: {e}", exc_info=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
