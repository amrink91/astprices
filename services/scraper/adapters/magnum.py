"""Парсер Magnum — REST API (reverse engineered)"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct


class MagnumScraper(AbstractStoreScraper):
    CITY_ID = 2  # Астана — ⚠️ верифицировать через mitmproxy!

    CATEGORIES_URL = f"{settings.magnum_base_url}/api/catalog/categories"
    PRODUCTS_URL   = f"{settings.magnum_base_url}/api/catalog/products"
    CITY_URL       = f"{settings.magnum_base_url}/api/user/city"

    def __init__(self) -> None:
        super().__init__("magnum")
        self._city_set = False

    async def _set_city(self) -> None:
        if self._city_set:
            return
        try:
            await self._post_json(self.CITY_URL, {"city_id": self.CITY_ID})
            self.logger.info(f"Magnum: город установлен city_id={self.CITY_ID}")
        except Exception as e:
            self.logger.warning(f"Не удалось установить город: {e}")
        self._city_set = True

    async def _get_categories(self) -> list[dict]:
        try:
            data = await self._get_json(self.CATEGORIES_URL, params={"city_id": self.CITY_ID})
            if isinstance(data, list):
                return data
            return data.get("categories", data.get("data", []))
        except Exception as e:
            self.logger.error(f"Ошибка категорий: {e}")
            return []

    async def _get_page(self, cat_id: str, page: int) -> tuple[list[dict], bool]:
        try:
            data = await self._get_json(self.PRODUCTS_URL, params={
                "category_id": cat_id,
                "city_id": self.CITY_ID,
                "page": page,
                "per_page": 48,
            })
            if isinstance(data, list):
                return data, len(data) == 48
            products = data.get("products", data.get("items", data.get("data", [])))
            has_next = data.get("has_next", data.get("hasNext", len(products) == 48))
            return products, has_next
        except Exception as e:
            self.logger.error(f"Ошибка страницы {page} кат.{cat_id}: {e}")
            return [], False

    def _parse(self, item: dict, cat_path: list[str]) -> Optional[RawProduct]:
        try:
            price = self.parse_price(str(
                item.get("price") or item.get("sell_price") or item.get("current_price") or 0
            ))
            if not price or price <= 0:
                return None

            sku = str(item.get("id") or item.get("sku") or "")
            name = (item.get("name") or item.get("title") or "").strip()
            if not sku or not name:
                return None

            images = item.get("images", [])
            img = images[0] if isinstance(images, list) and images else item.get("image_url")
            if isinstance(img, dict):
                img = img.get("url")

            old_price_raw = item.get("old_price") or item.get("original_price")
            old_price = self.parse_price(str(old_price_raw)) if old_price_raw else None

            return RawProduct(
                store_slug="magnum",
                store_sku=sku,
                name_raw=name,
                price_tenge=price,
                old_price_tenge=old_price,
                in_stock=bool(item.get("in_stock", item.get("available", True))),
                is_promoted=bool(old_price or item.get("is_promo")),
                promo_label=item.get("promo_label"),
                store_url=f"{settings.magnum_base_url}/product/{sku}",
                store_image_url=img or None,
                category_path=cat_path,
                unit=item.get("unit") or item.get("uom"),
                raw_json=item,
            )
        except Exception as e:
            self.logger.debug(f"Ошибка парсинга {item.get('id','?')}: {e}")
            return None

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        await self._set_city()
        categories = await self._get_categories()

        if not categories:
            self.logger.error("Magnum: категории не получены!")
            return

        self.logger.info(f"Magnum: {len(categories)} категорий")
        total = 0

        for cat in categories:
            cat_id = str(cat.get("id") or cat.get("category_id", ""))
            cat_name = cat.get("name") or cat.get("title", "?")
            if not cat_id:
                continue

            page = 0
            self.logger.info(f"  [{cat_name}]")

            while True:
                items, has_next = await self._get_page(cat_id, page)
                for item in items:
                    p = self._parse(item, [cat_name])
                    if p:
                        total += 1
                        yield p

                if not has_next or not items:
                    break
                page += 1

        self.logger.info(f"Magnum: итого {total} товаров")
