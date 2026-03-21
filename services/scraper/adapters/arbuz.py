"""Парсер Arbuz.kz — Playwright HTML scraping (SSR rendered)"""
from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

# Категории Arbuz Астана — ID и slug
CATEGORIES = [
    (225161, "moloko_syr_i_yaica", "Молоко, сыр и яйца"),
    (225162, "hleb_i_vypechka", "Хлеб и выпечка"),
    (225163, "ovoschi_frukty_i_yagody", "Овощи, фрукты и ягоды"),
    (225164, "myaso_ptica_i_kolbasy", "Мясо, птица и колбасы"),
    (225165, "ryba_i_moreprodukty", "Рыба и морепродукты"),
    (225167, "zamorozhennye_produkty", "Замороженные продукты"),
    (225168, "bakaleya", "Бакалея"),
    (225169, "napitki", "Напитки"),
    (225170, "sladosti_i_sneki", "Сладости и снеки"),
    (225171, "chay_kofe_i_kakao", "Чай, кофе и какао"),
    (225172, "sousy_i_pripravy", "Соусы и приправы"),
    (225173, "detskoe_pitanie", "Детское питание"),
    (225175, "zdorovoe_pitanie", "Здоровое питание"),
]


class ArbuzScraper(AbstractStoreScraper):
    CITY = "astana"  # в URL

    def __init__(self) -> None:
        super().__init__("arbuz")
        self._browser = None
        self._page = None

    async def _init_browser(self) -> None:
        if self._browser:
            return
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().__aenter__()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._page = await self._browser.new_page()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_pw'):
            await self._pw.__aexit__(None, None, None)
        await super().close()

    def _parse_price(self, text: str) -> Optional[Decimal]:
        """Извлекаем цену из текста вроде '435₸' или '8 304₸'"""
        digits = re.sub(r'[^\d]', '', text.split('₸')[0].strip())
        if digits:
            return Decimal(digits)
        return None

    async def _scrape_category(self, cat_id: int, cat_slug: str, cat_name: str) -> list[RawProduct]:
        """Парсим одну категорию через Playwright"""
        products = []
        url = f"https://arbuz.kz/ru/{self.CITY}/catalog/cat/{cat_id}-{cat_slug}"

        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._page.wait_for_timeout(3000)

            # Scroll down to load lazy content
            for _ in range(3):
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self._page.wait_for_timeout(1000)

            cards = await self._page.query_selector_all("article.product-card")
            self.logger.info(f"  [{cat_name}] {len(cards)} карточек")

            for card in cards:
                try:
                    link = await card.query_selector("a")
                    if not link:
                        continue

                    title = await link.get_attribute("title") or ""
                    href = await link.get_attribute("href") or ""
                    if not title:
                        continue

                    # Extract SKU from href: /ru/astana/catalog/item/251815-name
                    sku_match = re.search(r'/item/(\d+)', href)
                    sku = sku_match.group(1) if sku_match else ""
                    if not sku:
                        continue

                    # Get text content for price
                    text = await card.text_content() or ""

                    # Parse price: look for pattern like "435₸" or "8 304₸"
                    price_matches = re.findall(r'([\d\s]+)₸', text)
                    if not price_matches:
                        continue

                    # Last price number is usually the actual price
                    price = self._parse_price(price_matches[-1] + '₸')
                    if not price or price <= 0:
                        continue

                    # Old price if there's a strikethrough
                    old_price = None
                    if len(price_matches) >= 2:
                        old_p = self._parse_price(price_matches[0] + '₸')
                        if old_p and old_p > price:
                            old_price = old_p

                    # Image
                    img_el = await card.query_selector("img")
                    img_src = None
                    if img_el:
                        img_src = await img_el.get_attribute("src") or await img_el.get_attribute("data-src")

                    store_url = f"https://arbuz.kz{href}" if href.startswith("/") else href

                    products.append(RawProduct(
                        store_slug="arbuz",
                        store_sku=sku,
                        name_raw=title.strip(),
                        price_tenge=price,
                        old_price_tenge=old_price,
                        in_stock=True,
                        is_promoted=bool(old_price),
                        promo_label=None,
                        store_url=store_url,
                        store_image_url=img_src,
                        category_path=[cat_name],
                        unit=None,
                        raw_json={},
                    ))
                except Exception as e:
                    self.logger.debug(f"Card parse error: {e}")

        except Exception as e:
            self.logger.error(f"Category {cat_name} error: {e}")

        return products

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        await self._init_browser()

        self.logger.info(f"Arbuz: {len(CATEGORIES)} категорий")
        total = 0
        seen_skus = set()

        for cat_id, cat_slug, cat_name in CATEGORIES:
            products = await self._scrape_category(cat_id, cat_slug, cat_name)
            for p in products:
                if p.store_sku not in seen_skus:
                    seen_skus.add(p.store_sku)
                    total += 1
                    yield p

            # Small delay between categories
            await asyncio.sleep(1)

        self.logger.info(f"Arbuz: итого {total} товаров")
