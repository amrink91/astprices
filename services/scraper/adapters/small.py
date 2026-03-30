"""Парсер Small.kz через Wolt API — Playwright для auth + JSON API для товаров"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import AsyncIterator, Optional

from shared.scrapers.base import AbstractStoreScraper, RawProduct

logger = logging.getLogger("scraper.small")

# Wolt venue slug для Small Астана
WOLT_VENUE_SLUG = "small-ast15"
WOLT_BASE = "https://wolt.com/ru/kaz/nur-sultan/venue"
ASSORTMENT_API = "https://consumer-api.wolt.com/consumer-api/consumer-assortment/v1/venues/slug"

# Категории Small на Wolt (food only)
FOOD_CATEGORIES = [
    ("menucategory-7", "Бакалея"),
    ("menucategory-15", "Вода и напитки"),
    ("menucategory-21", "Готовая еда"),
    ("menucategory-29", "Для детей"),
    ("menucategory-42", "Заморозка"),
    ("menucategory-49", "Здоровое питание"),
    ("menucategory-56", "Колбасы и сосиски"),
    ("menucategory-63", "Консервы и соления"),
    ("menucategory-67", "Молочные продукты"),
    ("menucategory-73", "Кофе и чай"),
    ("menucategory-78", "Мясо и птица"),
    ("menucategory-83", "Овощи и фрукты"),
    ("menucategory-88", "Рыба и морепродукты"),
    ("menucategory-92", "Сладости и снеки"),
    ("menucategory-98", "Соусы и приправы"),
    ("menucategory-103", "Сыры"),
    ("menucategory-108", "Хлеб и выпечка"),
    ("menucategory-113", "Яйца и масло"),
]


class SmallScraper(AbstractStoreScraper):
    def __init__(self) -> None:
        super().__init__("small")
        self._browser = None
        self._page = None
        self._cookies_set = False

    async def _init_browser(self) -> None:
        if self._browser:
            return
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().__aenter__()
        self._browser = await self._pw.chromium.launch(headless=True)
        ctx = await self._browser.new_context(
            geolocation={"latitude": 51.145319, "longitude": 71.412776},
            permissions=["geolocation"]
        )
        self._page = await ctx.new_page()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_pw') and self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        await super().close()

    async def _setup_wolt_session(self) -> None:
        """Открываем Wolt, принимаем куки и устанавливаем геолокацию"""
        if self._cookies_set:
            return

        url = f"{WOLT_BASE}/{WOLT_VENUE_SLUG}"
        await self._page.goto(url, wait_until="networkidle", timeout=60000)
        await self._page.wait_for_timeout(2000)

        # Dismiss cookie consent
        consent = self._page.locator("text=Используйте только необходимые")
        if await consent.count() > 0:
            await consent.click()
            self.logger.info("Dismissed cookie consent")
            await self._page.wait_for_timeout(1000)

        # Share geolocation
        share_btn = self._page.locator("text=Поделиться местоположением")
        if await share_btn.count() > 0:
            await share_btn.click()
            self.logger.info("Shared geolocation")
            await self._page.wait_for_timeout(8000)
            await self._page.wait_for_load_state("networkidle")
            await self._page.wait_for_timeout(2000)

        self._cookies_set = True

    async def _scrape_category(self, cat_slug: str, cat_name: str) -> list[RawProduct]:
        """Скрапим категорию через Wolt, перехватывая API ответы"""
        products = []
        captured_items = []

        async def on_response(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if "json" in ct and "consumer-assortment" in url:
                try:
                    body = await response.body()
                    data = json.loads(body)
                    items = data.get("items", [])
                    captured_items.extend(items)
                except Exception:
                    pass

        self._page.on("response", on_response)

        try:
            cat_url = f"{WOLT_BASE}/{WOLT_VENUE_SLUG}/items/{cat_slug}"
            await self._page.goto(cat_url, wait_until="networkidle", timeout=60000)
            await self._page.wait_for_timeout(3000)

            # Scroll to load all pages (pagination via scroll)
            prev_count = 0
            for _ in range(30):
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self._page.wait_for_timeout(1500)
                if len(captured_items) == prev_count:
                    # No new items loaded, try one more scroll
                    await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await self._page.wait_for_timeout(2000)
                    if len(captured_items) == prev_count:
                        break
                prev_count = len(captured_items)

            # Parse captured items
            for item in captured_items:
                try:
                    name = item.get("name", "").strip()
                    if not name:
                        continue

                    price_raw = item.get("price", 0)
                    if not price_raw or price_raw <= 0:
                        continue
                    # Wolt prices in tiin (1/100 tenge)
                    price = Decimal(str(price_raw)) / 100

                    item_id = item.get("id", "")
                    barcode = item.get("barcode_gtin", "")
                    sku = barcode or item_id

                    old_price = None
                    orig = item.get("original_price")
                    if orig and orig > price_raw:
                        old_price = Decimal(str(orig)) / 100

                    # Image
                    images = item.get("images", [])
                    img_url = None
                    if images and isinstance(images[0], dict):
                        img_url = images[0].get("url", "")
                    elif images and isinstance(images[0], str):
                        img_url = images[0]

                    # Build Wolt product URL
                    store_url = f"{WOLT_BASE}/{WOLT_VENUE_SLUG}"

                    products.append(RawProduct(
                        store_slug="small",
                        store_sku=str(sku),
                        name_raw=name,
                        price_tenge=price,
                        old_price_tenge=old_price,
                        in_stock=True,
                        is_promoted=bool(old_price),
                        promo_label=None,
                        store_url=store_url,
                        store_image_url=img_url,
                        category_path=[cat_name],
                        unit=item.get("description"),
                        raw_json={},
                    ))
                except Exception as e:
                    self.logger.debug(f"Item parse error: {e}")

        except Exception as e:
            self.logger.error(f"Category {cat_name} error: {e}")
        finally:
            # Remove the response listener
            try:
                self._page.remove_listener("response", on_response)
            except Exception:
                pass

        self.logger.info(f"  [{cat_name}] {len(products)} товаров")
        return products

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        await self._init_browser()
        await self._setup_wolt_session()

        self.logger.info(f"Small (Wolt): {len(FOOD_CATEGORIES)} категорий")
        total = 0
        seen_skus = set()

        for cat_slug, cat_name in FOOD_CATEGORIES:
            products = await self._scrape_category(cat_slug, cat_name)

            for p in products:
                if p.store_sku not in seen_skus:
                    seen_skus.add(p.store_sku)
                    total += 1
                    yield p

            await asyncio.sleep(1)

        self.logger.info(f"Small (Wolt): итого {total} товаров")
