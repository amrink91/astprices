"""
Парсер Small.kz — Playwright (JS-рендеринг + защита от ботов)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import AsyncIterator, Optional

from playwright.async_api import async_playwright, Page, BrowserContext

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

logger = logging.getLogger("scraper.small")


class SmallScraper(AbstractStoreScraper):
    """
    Small.kz использует React SPA с lazy-loading.
    Playwright: перехватываем AJAX запросы параллельно с рендерингом.
    """

    def __init__(self) -> None:
        super().__init__("small")
        self._intercepted_responses: list[dict] = []

    async def _create_stealth_context(self, playwright):
        """Браузерный контекст с anti-detection"""
        browser = await playwright.chromium.launch(
            headless=settings.playwright_headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent=settings.random_user_agent,
            viewport={"width": 1366, "height": 768},
            locale="ru-KZ",
            timezone_id="Asia/Almaty",
            extra_http_headers={
                "Accept-Language": "ru-KZ,ru;q=0.9,kk;q=0.8",
            },
        )
        # Скрываем webdriver
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)
        return browser, context

    async def _get_category_urls(self, page: Page) -> list[tuple[str, str]]:
        """Получаем список категорий с главной страницы"""
        try:
            await page.goto(f"{settings.small_base_url}/catalog/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            links = await page.eval_on_selector_all(
                "a[href*='/catalog/']",
                """els => els
                    .map(el => ({href: el.href, text: el.innerText.trim()}))
                    .filter(x => x.text && x.href.includes('/catalog/') && x.href !== window.location.href)
                """,
            )
            # Убираем дубликаты
            seen = set()
            result = []
            for link in links:
                href = link["href"]
                text = link["text"]
                if href not in seen and text and len(text) < 60:
                    seen.add(href)
                    result.append((href, text))
            return result[:50]  # ограничиваем
        except Exception as e:
            logger.error(f"Ошибка получения категорий Small: {e}")
            return []

    async def _scrape_category_page(self, page: Page, url: str, cat_name: str) -> list[RawProduct]:
        """Парсим одну страницу категории"""
        products = []
        try:
            # Перехватываем API запросы
            api_data = []
            page.on("response", lambda r: api_data.append(r) if "/api/" in r.url and r.status == 200 else None)

            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)

            # Сначала пробуем через перехваченные API ответы
            for resp in api_data:
                try:
                    json_data = await resp.json()
                    parsed = self._parse_api_response(json_data, cat_name, resp.url)
                    if parsed:
                        products.extend(parsed)
                        break
                except Exception:
                    continue

            # Если API не сработал — парсим HTML
            if not products:
                products = await self._parse_html_products(page, cat_name)

        except Exception as e:
            logger.error(f"Ошибка парсинга страницы {url}: {e}")

        return products

    def _parse_api_response(self, data: dict, cat_name: str, url: str) -> list[RawProduct]:
        """Пробуем распознать товары из перехваченного API ответа"""
        items_candidates = []

        if isinstance(data, list):
            items_candidates = data
        elif isinstance(data, dict):
            for key in ["products", "items", "data", "results", "goods"]:
                if key in data and isinstance(data[key], list):
                    items_candidates = data[key]
                    break

        if not items_candidates:
            return []

        result = []
        for item in items_candidates:
            if not isinstance(item, dict):
                continue
            price = self.parse_price(str(
                item.get("price") or item.get("sell_price") or item.get("cost") or 0
            ))
            if not price or price <= 0:
                continue
            name = item.get("name") or item.get("title") or item.get("product_name", "")
            sku = str(item.get("id") or item.get("sku") or item.get("article", ""))
            if not name or not sku:
                continue

            old_price_raw = item.get("old_price") or item.get("compare_price")
            old_price = self.parse_price(str(old_price_raw)) if old_price_raw else None

            result.append(RawProduct(
                store_slug="small",
                store_sku=sku,
                name_raw=str(name).strip(),
                price_tenge=price,
                old_price_tenge=old_price,
                in_stock=bool(item.get("in_stock", item.get("available", True))),
                is_promoted=bool(old_price or item.get("promo")),
                promo_label=item.get("promo_label") or item.get("badge"),
                store_url=f"{settings.small_base_url}/product/{sku}",
                store_image_url=item.get("image") or item.get("photo") or item.get("img"),
                category_path=[cat_name],
                unit=item.get("unit"),
                raw_json=item,
            ))
        return result

    async def _parse_html_products(self, page: Page, cat_name: str) -> list[RawProduct]:
        """Fallback: CSS селекторы для товарных карточек"""
        try:
            # Распространённые CSS-паттерны для продуктовых карточек
            items_data = await page.eval_on_selector_all(
                ".product-card, .product-item, [class*='product'], [data-product]",
                """cards => cards.map(card => {
                    const nameEl  = card.querySelector('[class*="name"], [class*="title"], h3, h2');
                    const priceEl = card.querySelector('[class*="price"]:not([class*="old"])');
                    const oldEl   = card.querySelector('[class*="old-price"], [class*="compare"]');
                    const imgEl   = card.querySelector('img');
                    const linkEl  = card.querySelector('a[href]');
                    return {
                        name:      nameEl  ? nameEl.innerText.trim()  : '',
                        price:     priceEl ? priceEl.innerText.trim() : '',
                        old_price: oldEl   ? oldEl.innerText.trim()   : '',
                        img:       imgEl   ? (imgEl.src || imgEl.dataset.src || '') : '',
                        url:       linkEl  ? linkEl.href : '',
                        sku:       card.dataset.id || card.dataset.productId || card.dataset.sku || ''
                    };
                }).filter(x => x.name && x.price)
                """,
            )

            result = []
            for item in items_data:
                price = self.parse_price(item.get("price", ""))
                if not price or price <= 0:
                    continue
                name = item.get("name", "").strip()
                sku = item.get("sku") or item.get("url", "").split("/")[-1] or name[:20]
                old_price = self.parse_price(item.get("old_price", ""))
                result.append(RawProduct(
                    store_slug="small",
                    store_sku=str(sku),
                    name_raw=name,
                    price_tenge=price,
                    old_price_tenge=old_price,
                    in_stock=True,
                    is_promoted=bool(old_price),
                    store_url=item.get("url") or f"{settings.small_base_url}/catalog/",
                    store_image_url=item.get("img") or None,
                    category_path=[cat_name],
                ))
            return result
        except Exception as e:
            logger.error(f"HTML парсинг Small: {e}")
            return []

    async def _scroll_and_load_more(self, page: Page) -> None:
        """Прокрутка для загрузки lazy-load товаров"""
        prev_height = 0
        for _ in range(10):
            curr_height = await page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            prev_height = curr_height

            # Нажимаем "Загрузить ещё" если есть
            try:
                load_more = page.locator("button:has-text('Загрузить'), button:has-text('Ещё'), .load-more")
                if await load_more.count() > 0:
                    await load_more.first.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        async with async_playwright() as pw:
            browser, context = await self._create_stealth_context(pw)
            page = await context.new_page()

            category_urls = await self._get_category_urls(page)
            if not category_urls:
                logger.error("Small: категории не найдены!")
                await browser.close()
                return

            logger.info(f"Small: {len(category_urls)} категорий")
            total = 0

            for url, cat_name in category_urls:
                logger.info(f"  [{cat_name}]")
                await self._scroll_and_load_more(page)
                products = await self._scrape_category_page(page, url, cat_name)
                for p in products:
                    total += 1
                    yield p
                # Пауза между категориями
                await page.wait_for_timeout(settings.random_delay_ms)

            logger.info(f"Small: итого {total} товаров")
            await browser.close()
