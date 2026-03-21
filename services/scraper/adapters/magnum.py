"""Парсер Magnum — Strapi CMS API (magnum.kz:1337)"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct


class MagnumScraper(AbstractStoreScraper):
    BASE = "https://magnum.kz:1337"
    CATALOG_URL = f"{BASE}/api/new-product-catalog"
    PRODUCTS_URL = f"{BASE}/api/new-product"
    CITY = "astana"
    PAGE_SIZE = 100

    def __init__(self) -> None:
        super().__init__("magnum")

    async def _get_categories(self) -> list[dict]:
        try:
            data = await self._get_json(self.CATALOG_URL, params={"city": self.CITY})
            if isinstance(data, list):
                return data
            return data.get("data", [])
        except Exception as e:
            self.logger.error(f"Ошибка категорий: {e}")
            return []

    async def _get_products(self, catalog_id: Optional[int] = None) -> list[dict]:
        """Получаем товары с пагинацией"""
        all_products = []
        offset = 0

        while True:
            params = {"city": self.CITY, "cunt": self.PAGE_SIZE}
            if catalog_id:
                params["catalog"] = catalog_id

            try:
                data = await self._get_json(self.PRODUCTS_URL, params=params)
                if not isinstance(data, list):
                    data = data.get("data", [])
            except Exception as e:
                self.logger.error(f"Ошибка товаров catalog={catalog_id}: {e}")
                break

            all_products.extend(data)

            if len(data) < self.PAGE_SIZE:
                break
            offset += self.PAGE_SIZE
            # Strapi API Magnum не поддерживает offset, выходим
            break

        return all_products

    def _parse(self, item: dict, cat_name: str) -> Optional[RawProduct]:
        try:
            price_raw = item.get("final_price") or item.get("start_price") or 0
            price = Decimal(str(price_raw))
            if not price or price <= 0:
                return None

            name = (item.get("name") or "").strip()
            sku = str(item.get("id", ""))
            if not name or not sku:
                return None

            old_price_raw = item.get("start_price")
            old_price = Decimal(str(old_price_raw)) if old_price_raw and old_price_raw != price_raw else None

            img = item.get("image")
            if img and not img.startswith("http"):
                img = f"{self.BASE}{img}"

            discount = item.get("discount")
            is_promoted = bool(discount and discount > 0)
            discount_type = item.get("discount_type", {})
            promo_label = discount_type.get("label") if isinstance(discount_type, dict) else None

            return RawProduct(
                store_slug="magnum",
                store_sku=sku,
                name_raw=name,
                price_tenge=price,
                old_price_tenge=old_price,
                in_stock=True,
                is_promoted=is_promoted,
                promo_label=promo_label,
                store_url=f"{settings.magnum_base_url}/product/{sku}",
                store_image_url=img,
                category_path=[cat_name] if cat_name else [],
                unit=None,
                raw_json=item,
            )
        except Exception as e:
            self.logger.debug(f"Ошибка парсинга {item.get('id','?')}: {e}")
            return None

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        categories = await self._get_categories()
        if not categories:
            self.logger.error("Magnum: категории не получены!")
            return

        self.logger.info(f"Magnum: {len(categories)} категорий")
        total = 0
        seen_ids = set()

        for cat in categories:
            cat_id = cat.get("id")
            cat_name = cat.get("label") or cat.get("name", "?")
            if not cat_id:
                continue

            self.logger.info(f"  [{cat_name}]")
            products = await self._get_products(cat_id)

            for item in products:
                pid = item.get("id")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                p = self._parse(item, cat_name)
                if p:
                    total += 1
                    yield p

        self.logger.info(f"Magnum: итого {total} товаров")
