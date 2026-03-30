"""Парсер Galmart.kz — Playwright HTML scraping (JS-rendered)"""
from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

logger = logging.getLogger("scraper.galmart")

# Продуктовые категории Galmart Астана — (path, name)
FOOD_CATEGORIES = [
    ("/catalog/items/4/2", "Йогурты"),
    ("/catalog/items/4/3", "Кисломолочные продукты"),
    ("/catalog/items/4/8", "Масло сливочное, спреды"),
    ("/catalog/items/4/6", "Молоко, сливки"),
    ("/catalog/items/4/9", "Сыры"),
    ("/catalog/items/4/85", "Творог, творожные десерты"),
    ("/catalog/items/4/4", "Яйцо"),
    ("/catalog/items/6/16", "Овощи"),
    ("/catalog/items/6/5", "Фрукты"),
    ("/catalog/items/6/7", "Ягоды"),
    ("/catalog/items/6/15", "Зелень"),
    ("/catalog/items/2/108", "Булочки"),
    ("/catalog/items/2/109", "Выпечка"),
    ("/catalog/items/2/107", "Хлеб"),
    ("/catalog/items/13/30", "Колбасы"),
    ("/catalog/items/13/27", "Сосиски, сардельки"),
    ("/catalog/items/1/26", "Мясо охлажденное"),
    ("/catalog/items/1/24", "Птица"),
    ("/catalog/items/3/32", "Рыба"),
    ("/catalog/items/3/33", "Морепродукты"),
    ("/catalog/items/14/37", "Полуфабрикаты замороженные"),
    ("/catalog/items/14/39", "Овощи замороженные"),
    ("/catalog/items/8/40", "Крупы, макароны"),
    ("/catalog/items/8/41", "Масла растительные"),
    ("/catalog/items/8/42", "Мука, соль, сахар"),
    ("/catalog/items/8/43", "Приправы, соусы, специи"),
    ("/catalog/items/12/10", "Кофе"),
    ("/catalog/items/12/1", "Чай"),
    ("/catalog/items/16/47", "Вода"),
    ("/catalog/items/16/49", "Напитки, лимонады"),
    ("/catalog/items/16/48", "Соки, нектары"),
    ("/catalog/items/24/134", "Печенье, вафли"),
    ("/catalog/items/24/133", "Шоколад, батончики"),
    ("/catalog/items/15/11", "Детское питание"),
]


class GalmartScraper(AbstractStoreScraper):

    def __init__(self) -> None:
        super().__init__("galmart")
        self._browser = None
        self._page = None

    async def _init_browser(self) -> None:
        if self._browser:
            return
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().__aenter__()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        self._api_urls = []

        # Intercept network requests to discover product API
        async def on_response(response):
            url = response.url
            if '/catalog/' in url or '/items/' in url or '/product/' in url or '/api/' in url:
                if response.status == 200 and 'json' in (response.headers.get('content-type', '') or ''):
                    self._api_urls.append(url)
                    logger.info(f"Discovered API: {url}")

        self._page.on("response", on_response)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_pw') and self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        await super().close()

    async def _extract_items(self) -> list[dict]:
        """Извлекаем товары со страницы через JS"""
        return await self._page.evaluate("""() => {
            const cards = document.querySelectorAll('.product');
            return Array.from(cards).map(card => {
                const nameEl = card.querySelector('.name');
                const plusMinus = card.querySelector('.plus_minus');
                const imgEl = card.querySelector('.photos img');
                const priceEl = card.querySelector('.price');

                let price = plusMinus ? plusMinus.getAttribute('data-price') : null;
                let oldPrice = null;

                if (priceEl) {
                    const priceText = priceEl.textContent;
                    const matches = priceText.match(/(\d[\d\s]*)₸/g);
                    if (matches && matches.length >= 2 && price) {
                        oldPrice = matches[0].replace(/[^\d]/g, '');
                    } else if (!price && matches && matches.length >= 1) {
                        price = matches[matches.length - 1].replace(/[^\d]/g, '');
                    }
                }

                return {
                    id: card.getAttribute('data-id') || '',
                    name: nameEl ? nameEl.textContent.trim() : '',
                    price: price || '',
                    oldPrice: oldPrice || '',
                    img: imgEl ? imgEl.getAttribute('src') : '',
                };
            }).filter(x => x.name && x.price);
        }""")

    def _parse_items(self, items: list[dict], path: str, cat_name: str) -> list[RawProduct]:
        """Парсим извлечённые товары в RawProduct"""
        products = []
        for item in items:
            try:
                price = Decimal(item["price"]) if item["price"] else None
                if not price or price <= 0:
                    continue

                old_price = None
                if item.get("oldPrice"):
                    old_p = Decimal(item["oldPrice"])
                    if old_p > price:
                        old_price = old_p

                sku = item.get("id") or ""
                if not sku:
                    continue

                img = item.get("img", "")
                if img and not img.startswith("http"):
                    img = f"https://galmart.kz{img}"

                products.append(RawProduct(
                    store_slug="galmart",
                    store_sku=sku,
                    name_raw=item["name"],
                    price_tenge=price,
                    old_price_tenge=old_price,
                    in_stock=True,
                    is_promoted=bool(old_price),
                    promo_label=None,
                    store_url=f"https://galmart.kz{path}",
                    store_image_url=img or None,
                    category_path=[cat_name],
                    unit=None,
                    raw_json={},
                ))
            except Exception as e:
                self.logger.debug(f"Card parse error: {e}")
        return products

    async def _scrape_category(self, path: str, cat_name: str) -> list[RawProduct]:
        """Парсим категорию, кликая 'Загрузить ещё' для подгрузки всех товаров"""
        url = f"https://galmart.kz{path}"

        try:
            await self._page.goto(url, wait_until="networkidle", timeout=60000)
            await self._page.wait_for_timeout(3000)

            # Scroll down to trigger initial load
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._page.wait_for_timeout(2000)

            # Debug: log what buttons/elements contain "загрузить" or "еще"
            debug_info = await self._page.evaluate(r"""() => {
                const results = [];
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    if (el.children.length === 0) {  // leaf nodes only
                        const text = el.textContent.trim().toLowerCase();
                        if (text.includes('загрузить') || text.includes('еще') || text.includes('ещё') || text.includes('показать')) {
                            results.push({
                                tag: el.tagName,
                                text: el.textContent.trim(),
                                classes: el.className,
                                visible: el.offsetParent !== null,
                                parent: el.parentElement ? el.parentElement.tagName + '.' + el.parentElement.className : ''
                            });
                        }
                    }
                }
                return results;
            }""")
            if debug_info:
                self.logger.info(f"  [{cat_name}] Load more candidates: {debug_info}")

            if self._api_urls:
                self.logger.info(f"  [{cat_name}] API URLs found: {self._api_urls}")
                self._api_urls.clear()

            # Click "Загрузить ещё" repeatedly until no more products load
            click_count = 0
            while click_count < 50:
                prev_count = await self._page.evaluate("document.querySelectorAll('.product').length")

                # Try to find and click "Загрузить еще" via JS — match any element containing the text
                clicked = await self._page.evaluate(r"""() => {
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {
                        if (el.children.length > 0) continue;  // only leaf nodes
                        const text = el.textContent.trim();
                        if ((text === 'Загрузить еще' || text === 'Загрузить ещё' ||
                             text === 'Показать ещё' || text === 'Показать еще' ||
                             text.toLowerCase().includes('загрузить еще')) &&
                            el.offsetParent !== null) {
                            el.click();
                            return 'clicked: ' + el.tagName + ' ' + text;
                        }
                    }
                    // Also try clicking the parent of text node
                    for (const el of allElements) {
                        const text = el.textContent.trim();
                        if (text === 'Загрузить еще' || text === 'Загрузить ещё') {
                            if (el.parentElement) {
                                el.parentElement.click();
                                return 'clicked parent: ' + el.parentElement.tagName;
                            }
                        }
                    }
                    return false;
                }""")

                if not clicked:
                    break

                await self._page.wait_for_timeout(3000)

                # Scroll to bottom after loading
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self._page.wait_for_timeout(1000)

                new_count = await self._page.evaluate("document.querySelectorAll('.product').length")
                if new_count <= prev_count:
                    break

                click_count += 1

            items = await self._extract_items()
            products = self._parse_items(items, path, cat_name)
            self.logger.info(f"  [{cat_name}] {len(products)} товаров (clicks: {click_count})")
            return products

        except Exception as e:
            self.logger.error(f"Category {cat_name} error: {e}")
            return []

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        await self._init_browser()

        self.logger.info(f"Galmart: {len(FOOD_CATEGORIES)} категорий")
        total = 0
        seen_skus = set()

        for path, cat_name in FOOD_CATEGORIES:
            products = await self._scrape_category(path, cat_name)
            for p in products:
                if p.store_sku not in seen_skus:
                    seen_skus.add(p.store_sku)
                    total += 1
                    yield p

            await asyncio.sleep(1)

        self.logger.info(f"Galmart: итого {total} товаров")
