"""Парсер Arbuz.kz — GraphQL API"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

CATEGORIES_QUERY = """
query GetCategories($cityId: Int!) {
  categories(cityId: $cityId) {
    id name slug parent_id
    children { id name slug }
  }
}
"""

PRODUCTS_QUERY = """
query GetProducts($categoryId: Int!, $cityId: Int!, $page: Int!, $perPage: Int!) {
  categoryProducts(categoryId: $categoryId, cityId: $cityId, page: $page, perPage: $perPage) {
    items {
      id sku name slug price oldPrice unit weight inStock isPromo promoLabel
      images { url }
    }
    pagination { hasNextPage }
  }
}
"""


class ArbuzScraper(AbstractStoreScraper):
    # ⚠️ city_id для Астаны — верифицировать через browser devtools!
    CITY_ID = 2

    def __init__(self) -> None:
        super().__init__("arbuz")
        self._client.headers.update({
            "Content-Type": "application/json",
            "x-requested-with": "XMLHttpRequest",
            "Referer": settings.arbuz_base_url,
            "Origin": settings.arbuz_base_url,
        })

    async def _init_session(self) -> None:
        """Получаем cookies через главную страницу"""
        try:
            await self._client.get(f"{settings.arbuz_base_url}/ru/astana")
            self.logger.info("Arbuz: сессия инициализирована")
        except Exception as e:
            self.logger.warning(f"Arbuz сессия: {e}")

    async def _gql(self, query: str, variables: dict) -> dict:
        data = await self._post_json(
            settings.arbuz_graphql_url,
            json_data={"query": query, "variables": variables},
        )
        if "errors" in data and not data.get("data"):
            raise Exception(f"GraphQL errors: {data['errors']}")
        return data.get("data", {})

    async def _get_categories(self) -> list[dict]:
        try:
            data = await self._gql(CATEGORIES_QUERY, {"cityId": self.CITY_ID})
            return data.get("categories", [])
        except Exception as e:
            self.logger.error(f"Категории Arbuz: {e}")
            return []

    def _flatten(self, cats: list[dict], path: list[str] = None) -> list[tuple[dict, list[str]]]:
        path = path or []
        result = []
        for cat in cats:
            current = path + [cat["name"]]
            result.append((cat, current))
            if cat.get("children"):
                result.extend(self._flatten(cat["children"], current))
        return result

    async def _get_page(self, cat_id: int, page: int) -> tuple[list[dict], bool]:
        try:
            data = await self._gql(PRODUCTS_QUERY, {
                "categoryId": cat_id, "cityId": self.CITY_ID,
                "page": page, "perPage": 40,
            })
            cd = data.get("categoryProducts", {})
            return cd.get("items", []), cd.get("pagination", {}).get("hasNextPage", False)
        except Exception as e:
            self.logger.error(f"Страница {page} кат.{cat_id}: {e}")
            return [], False

    def _parse(self, item: dict, cat_path: list[str]) -> Optional[RawProduct]:
        try:
            price = self.parse_price(str(item.get("price", 0)))
            if not price or price <= 0:
                return None

            sku = str(item.get("id") or item.get("sku", ""))
            name = item.get("name", "").strip()
            if not sku or not name:
                return None

            images = item.get("images", [])
            img = images[0].get("url") if images else None
            old_price_raw = item.get("oldPrice")
            old_price = self.parse_price(str(old_price_raw)) if old_price_raw else None

            return RawProduct(
                store_slug="arbuz",
                store_sku=sku,
                name_raw=name,
                price_tenge=price,
                old_price_tenge=old_price,
                in_stock=bool(item.get("inStock", True)),
                is_promoted=bool(item.get("isPromo", False)),
                promo_label=item.get("promoLabel"),
                store_url=f"{settings.arbuz_base_url}/ru/astana/product/{item.get('slug', sku)}",
                store_image_url=img,
                category_path=cat_path,
                unit=item.get("unit") or item.get("weight"),
                raw_json=item,
            )
        except Exception as e:
            self.logger.debug(f"Ошибка парсинга Arbuz {item.get('id','?')}: {e}")
            return None

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        await self._init_session()
        cats_tree = await self._get_categories()

        if not cats_tree:
            self.logger.error("Arbuz: категории не получены!")
            return

        flat = self._flatten(cats_tree)
        self.logger.info(f"Arbuz: {len(flat)} категорий")
        total = 0

        for cat, path in flat:
            if cat.get("children"):
                continue  # только листовые категории

            cat_id = int(cat["id"])
            page = 1
            self.logger.info(f"  [{' > '.join(path)}]")

            while True:
                items, has_next = await self._get_page(cat_id, page)
                for item in items:
                    p = self._parse(item, path)
                    if p:
                        total += 1
                        yield p

                if not has_next or not items:
                    break
                page += 1

        self.logger.info(f"Arbuz: итого {total} товаров")
