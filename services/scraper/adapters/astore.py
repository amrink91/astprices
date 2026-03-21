"""
Парсер A-Store (a-store.kz) — Next.js + REST API
Премиальный продуктовый магазин в Астане.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

logger = logging.getLogger("scraper.astore")


class AStoreScraper(AbstractStoreScraper):

    # Next.js API routes — верифицировать через network inspector
    CATEGORIES_URL = f"{settings.astore_base_url}/api/categories"
    PRODUCTS_URL   = f"{settings.astore_base_url}/api/products"

    def __init__(self) -> None:
        super().__init__("astore")
        self._client.headers.update({
            "Referer": settings.astore_base_url,
            "Origin": settings.astore_base_url,
            "X-Requested-With": "XMLHttpRequest",
        })

    async def _get_categories(self) -> list[dict]:
        try:
            data = await self._get_json(self.CATEGORIES_URL)
            if isinstance(data, list):
                return data
            return data.get("categories", data.get("data", []))
        except Exception as e:
            logger.error(f"A-Store категории: {e}")
            return []

    async def _get_products_page(self, category_slug: str, page: int = 1) -> tuple[list[dict], bool]:
        try:
            data = await self._get_json(self.PRODUCTS_URL, params={
                "category": category_slug,
                "page": page,
                "limit": 20,
            })
            if isinstance(data, list):
                return data, len(data) == 20
            items = data.get("products", data.get("data", data.get("items", [])))
            total = data.get("total", data.get("count", 0))
            has_next = data.get("hasNext", page * 20 < total)
            return items, has_next
        except Exception as e:
            logger.error(f"A-Store товары кат={category_slug} стр={page}: {e}")
            return [], False

    def _parse(self, item: dict, cat_path: list[str]) -> Optional[RawProduct]:
        try:
            price = self.parse_price(str(item.get("price") or item.get("cost") or 0))
            if not price or price <= 0:
                return None

            sku = str(item.get("id") or item.get("sku") or item.get("slug") or "")
            name = (item.get("name") or item.get("title") or "").strip()
            if not sku or not name:
                return None

            old_price_raw = item.get("oldPrice") or item.get("comparePrice") or item.get("old_price")
            old_price = self.parse_price(str(old_price_raw)) if old_price_raw else None

            img = (item.get("image") or item.get("photo") or item.get("thumbnail") or "")
            if img and not img.startswith("http"):
                img = settings.astore_base_url + img

            slug = item.get("slug") or sku
            return RawProduct(
                store_slug="astore",
                store_sku=sku,
                name_raw=name,
                price_tenge=price,
                old_price_tenge=old_price,
                in_stock=bool(item.get("inStock", item.get("available", True))),
                is_promoted=bool(old_price or item.get("isPromo")),
                promo_label=item.get("promoLabel"),
                store_url=f"{settings.astore_base_url}/product/{slug}",
                store_image_url=img or None,
                category_path=cat_path,
                unit=item.get("unit") or item.get("weight"),
                raw_json=item,
            )
        except Exception as e:
            logger.debug(f"A-Store parse: {e}")
            return None

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        categories = await self._get_categories()
        if not categories:
            logger.error("A-Store: нет категорий!")
            return

        logger.info(f"A-Store: {len(categories)} категорий")
        total = 0

        for cat in categories:
            slug = cat.get("slug") or cat.get("id") or str(cat)
            name = cat.get("name") or cat.get("title") or str(slug)
            page = 1
            logger.info(f"  [{name}]")

            while True:
                items, has_next = await self._get_products_page(str(slug), page)
                for item in items:
                    p = self._parse(item, [name])
                    if p:
                        total += 1
                        yield p

                if not has_next or not items:
                    break
                page += 1

        logger.info(f"A-Store: итого {total} товаров")
