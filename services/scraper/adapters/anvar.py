"""
Парсер Анвар (anvar.kz) — Playwright + перехват ASTOR Tech API
Анвар использует платформу ASTOR Tech (мобильное приложение: com.astor.loyalty.mobile.anvar)
Сайт: https://www.anvar.kz/catalog/
"""
from __future__ import annotations

import json
import logging
import re
from typing import AsyncIterator, Optional

from playwright.async_api import async_playwright, Page, Route, Request

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

logger = logging.getLogger("scraper.anvar")


class AnvarScraper(AbstractStoreScraper):
    """
    Анвар — гипермаркет в Астане (сеть с 1993 года).
    Сайт на базе ASTOR Tech CMS.
    Стратегия:
      1. Playwright открывает каталог с перехватом сетевых запросов
      2. Ищем ASTOR API эндпоинты в перехваченных ответах
      3. Если API найдено → переключаемся на httpx для масштабирования
      4. Fallback: парсим HTML напрямую
    """

    def __init__(self) -> None:
        super().__init__("anvar")
        self._api_base: Optional[str] = None     # обнаруженный API эндпоинт
        self._api_headers: dict = {}              # заголовки для API
        self._intercepted_products: list[dict] = []

    async def _discover_api(self, page: Page) -> None:
        """
        Перехватываем сетевые запросы чтобы найти API Анвара.
        ASTOR платформа обычно имеет: /api/v1/products, /catalog/get, /goods/list
        """
        intercepted = []

        async def handle_response(response):
            url = response.url
            # Ищем ответы с JSON массивами (вероятно товары)
            if (response.status == 200
                    and any(kw in url for kw in ["/api/", "/catalog/get", "/goods", "/products", "/items"])
                    and "application/json" in (response.headers.get("content-type") or "")):
                try:
                    body = await response.json()
                    intercepted.append({"url": url, "data": body, "headers": dict(response.headers)})
                    logger.info(f"Анвар: перехвачен API ответ: {url}")
                except Exception:
                    pass

        page.on("response", handle_response)

        await page.goto(settings.anvar_base_url + "/catalog/", wait_until="networkidle", timeout=40000)
        await page.wait_for_timeout(3000)

        # Скроллим чтобы спровоцировать lazy-load
        await page.evaluate("window.scrollTo(0, 500)")
        await page.wait_for_timeout(1500)

        # Анализируем перехваченные запросы
        for item in intercepted:
            data = item["data"]
            # Проверяем похожи ли данные на список товаров
            items_list = None
            if isinstance(data, list) and len(data) > 0:
                items_list = data
            elif isinstance(data, dict):
                for key in ["products", "goods", "items", "data", "catalog", "results"]:
                    if key in data and isinstance(data[key], list) and len(data[key]) > 0:
                        items_list = data[key]
                        break

            if items_list and isinstance(items_list[0], dict):
                # Проверяем наличие характерных полей товара
                first = items_list[0]
                if any(k in first for k in ["price", "name", "title", "cost", "NAME", "PRICE"]):
                    self._api_base = item["url"].rsplit("?", 1)[0]
                    self._intercepted_products = items_list
                    logger.info(f"Анвар: обнаружен API: {self._api_base} ({len(items_list)} товаров в первом ответе)")
                    return

        logger.warning("Анвар: API не обнаружен, будем парсить HTML")

    async def _get_category_links(self, page: Page) -> list[tuple[str, str]]:
        """Список категорий с каталога"""
        try:
            links = await page.eval_on_selector_all(
                "a[href*='/catalog/']",
                """els => els
                    .map(e => ({href: e.href, text: e.innerText.trim()}))
                    .filter(x => x.text.length > 1 && x.text.length < 60
                                && x.href.includes('/catalog/')
                                && !x.href.endsWith('/catalog/'))
                    .filter((x, i, arr) => arr.findIndex(y => y.href === x.href) === i)
                """,
            )
            return [(lnk["href"], lnk["text"]) for lnk in links[:60]]
        except Exception as e:
            logger.error(f"Анвар: ошибка категорий: {e}")
            return []

    async def _scrape_page_html(self, page: Page, url: str, cat_name: str) -> list[RawProduct]:
        """Прямой HTML парсинг страницы категории"""
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Скроллим для загрузки всех товаров
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 800)")
                await page.wait_for_timeout(800)

            items_data = await page.eval_on_selector_all(
                "[class*='product'], [class*='good'], [class*='item'], [class*='card']",
                """cards => cards.map(card => {
                    const name  = card.querySelector('[class*="name"], [class*="title"], h3, h4');
                    const price = card.querySelector('[class*="price"]:not([class*="old"]):not([class*="prev"])');
                    const old   = card.querySelector('[class*="old"], [class*="prev"], s');
                    const img   = card.querySelector('img[src], img[data-src]');
                    const link  = card.querySelector('a[href*="/catalog/"], a[href*="/product/"], a[href*="/good/"]');
                    return {
                        name:  name  ? name.innerText.trim()  : '',
                        price: price ? price.innerText.trim() : '',
                        old:   old   ? old.innerText.trim()   : '',
                        img:   img   ? (img.src || img.dataset.src || '') : '',
                        href:  link  ? link.href : '',
                        id:    card.dataset.id || card.dataset.goodId || card.id || ''
                    }
                }).filter(x => x.name && x.price)
                """,
            )

            result = []
            for item in items_data:
                price = self.parse_price(item.get("price", ""))
                if not price or price <= 0:
                    continue

                name = item.get("name", "").strip()
                sku = item.get("id") or re.search(r"/(\d+)/?$", item.get("href", ""))
                sku = sku.group(1) if hasattr(sku, "group") else str(sku or name[:30])

                old_price = self.parse_price(item.get("old", ""))
                img = item.get("img", "")
                if img and not img.startswith("http"):
                    img = settings.anvar_base_url + img

                result.append(RawProduct(
                    store_slug="anvar",
                    store_sku=sku,
                    name_raw=name,
                    price_tenge=price,
                    old_price_tenge=old_price,
                    in_stock=True,
                    is_promoted=bool(old_price),
                    store_url=item.get("href") or f"{settings.anvar_base_url}/catalog/",
                    store_image_url=img or None,
                    category_path=[cat_name],
                ))
            return result

        except Exception as e:
            logger.error(f"Анвар HTML: {e}")
            return []

    def _parse_api_item(self, item: dict, cat_name: str) -> Optional[RawProduct]:
        """Парсинг товара из перехваченного API ответа"""
        try:
            # ASTOR API может использовать разные имена полей
            price = self.parse_price(str(
                item.get("price") or item.get("PRICE") or item.get("cost") or
                item.get("Price") or item.get("retail_price") or 0
            ))
            if not price or price <= 0:
                return None

            name = (item.get("name") or item.get("NAME") or item.get("title") or item.get("good_name") or "").strip()
            sku = str(item.get("id") or item.get("ID") or item.get("sku") or item.get("good_id") or "")
            if not name or not sku:
                return None

            old_price_raw = item.get("old_price") or item.get("OLD_PRICE") or item.get("base_price")
            old_price = self.parse_price(str(old_price_raw)) if old_price_raw else None

            img = (item.get("image") or item.get("img") or item.get("PREVIEW_PICTURE") or
                   item.get("photo") or item.get("picture") or "")
            if img and isinstance(img, dict):
                img = img.get("src") or img.get("url") or ""
            if img and not str(img).startswith("http"):
                img = settings.anvar_base_url + str(img)

            return RawProduct(
                store_slug="anvar",
                store_sku=sku,
                name_raw=name,
                price_tenge=price,
                old_price_tenge=old_price,
                in_stock=bool(item.get("in_stock", item.get("available", item.get("quantity", 1)))),
                is_promoted=bool(old_price),
                store_url=f"{settings.anvar_base_url}/catalog/{sku}/",
                store_image_url=str(img) if img else None,
                category_path=[cat_name],
                raw_json=item,
            )
        except Exception as e:
            logger.debug(f"Анвар parse: {e}")
            return None

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=settings.playwright_headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=settings.random_user_agent,
                locale="ru-KZ",
                timezone_id="Asia/Almaty",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()

            # Обнаруживаем API
            await self._discover_api(page)

            # Если нашли API — сначала отдаём перехваченные товары
            total = 0
            if self._intercepted_products:
                logger.info(f"Анвар: используем перехваченный API, {len(self._intercepted_products)} товаров")
                for item in self._intercepted_products:
                    p = self._parse_api_item(item, "Каталог")
                    if p:
                        total += 1
                        yield p

            # Получаем категории для полного обхода
            category_links = await self._get_category_links(page)
            logger.info(f"Анвар: {len(category_links)} категорий для обхода")

            for url, cat_name in category_links:
                logger.info(f"  [{cat_name}]")
                products = await self._scrape_page_html(page, url, cat_name)
                for p in products:
                    total += 1
                    yield p
                await page.wait_for_timeout(settings.random_delay_ms)

            logger.info(f"Анвар: итого {total} товаров")
            await browser.close()
