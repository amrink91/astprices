"""
Парсер Galmart.kz — Bitrix-based CMS
Стратегия: Playwright получает сессию + iblock IDs, httpx делает AJAX запросы.
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Optional

from playwright.async_api import async_playwright

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

logger = logging.getLogger("scraper.galmart")


class GalmartScraper(AbstractStoreScraper):

    # Bitrix AJAX endpoint
    AJAX_URL = f"{settings.galmart_base_url}/bitrix/services/main/ajax.php"

    def __init__(self) -> None:
        super().__init__("galmart")
        self._session_cookies: dict = {}
        self._bitrix_sessid: str = ""

    async def _init_bitrix_session(self) -> list[dict]:
        """
        Playwright открывает каталог, извлекает:
        - PHPSESSID cookie
        - bitrix_sessid (CSRF токен)
        - Список разделов (iblock sections) с их ID
        """
        categories = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=settings.playwright_headless)
            context = await browser.new_context(
                user_agent=settings.random_user_agent,
                locale="ru-KZ",
            )
            page = await context.new_page()

            try:
                await page.goto(f"{settings.galmart_base_url}/catalog/", wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # Извлекаем CSRF токен Bitrix из JS
                self._bitrix_sessid = await page.evaluate("""
                    () => {
                        if (window.BX && BX.bitrix_sessid) return BX.bitrix_sessid();
                        const m = document.body.innerHTML.match(/bitrix_sessid['":\s]+['"]([a-f0-9]+)['"]/);
                        return m ? m[1] : '';
                    }
                """)

                # Получаем cookies
                cookies = await context.cookies()
                self._session_cookies = {c["name"]: c["value"] for c in cookies}

                # Ссылки на категории
                links = await page.eval_on_selector_all(
                    "a[href*='/catalog/']",
                    """els => els
                        .map(e => ({href: e.href, text: e.innerText.trim(), dataset: e.dataset}))
                        .filter(x => x.text && x.href.includes('/catalog/') && x.text.length < 50)
                    """,
                )

                seen = set()
                for link in links:
                    href = link["href"]
                    if href not in seen:
                        seen.add(href)
                        # Извлекаем section ID из URL или data-атрибутов
                        section_id = link.get("dataset", {}).get("section") or self._extract_id_from_url(href)
                        categories.append({
                            "url": href,
                            "name": link["text"],
                            "section_id": section_id,
                        })

                logger.info(f"Galmart: сессия инициализирована, {len(categories)} категорий")

            except Exception as e:
                logger.error(f"Galmart Playwright: {e}")
            finally:
                await browser.close()

        return categories

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Извлекаем числовой ID из URL типа /catalog/section123/ или /catalog/meat/"""
        match = re.search(r"/catalog/[^/]*?(\d+)", url)
        return match.group(1) if match else None

    async def _get_section_products(self, section_url: str, cat_name: str, page_num: int = 1) -> tuple[list[RawProduct], bool]:
        """
        Bitrix AJAX запрос за товарами секции.
        Если AJAX не работает — парсим HTML через httpx.
        """
        products = []
        has_next = False

        # Метод 1: Bitrix component call
        try:
            url_with_page = f"{section_url}?PAGEN_1={page_num}"
            data = await self._get_json(
                self.AJAX_URL,
                params={
                    "action": "catalog.product.list",
                    "mode": "ajax",
                    "page": page_num,
                },
                headers={
                    **self._client.headers,
                    "X-Bitrix-Csrf-Token": self._bitrix_sessid,
                    "Cookie": "; ".join(f"{k}={v}" for k, v in self._session_cookies.items()),
                    "Referer": section_url,
                },
            )
            # Пробуем разные структуры ответа Bitrix
            items = data.get("data", {}).get("items", data.get("items", []))
            has_next = data.get("data", {}).get("hasNextPage", data.get("hasNextPage", False))

            for item in items:
                p = self._parse_bitrix_product(item, cat_name)
                if p:
                    products.append(p)

        except Exception:
            # Метод 2: HTML парсинг страницы
            products, has_next = await self._parse_html_page(section_url, cat_name, page_num)

        return products, has_next

    def _parse_bitrix_product(self, item: dict, cat_name: str) -> Optional[RawProduct]:
        try:
            price = self.parse_price(str(item.get("PRICE") or item.get("price") or item.get("CATALOG_PRICE_1") or 0))
            if not price or price <= 0:
                return None

            sku = str(item.get("ID") or item.get("id") or item.get("CODE") or "")
            name = item.get("NAME") or item.get("name") or ""
            if not sku or not name:
                return None

            old_price_raw = item.get("OLD_PRICE") or item.get("CATALOG_COMPARE_PRICE")
            old_price = self.parse_price(str(old_price_raw)) if old_price_raw else None

            # Изображение
            detail_picture = item.get("DETAIL_PICTURE") or item.get("PREVIEW_PICTURE") or {}
            img_url = detail_picture.get("SRC") if isinstance(detail_picture, dict) else str(detail_picture)
            if img_url and not img_url.startswith("http"):
                img_url = settings.galmart_base_url + img_url

            return RawProduct(
                store_slug="galmart",
                store_sku=sku,
                name_raw=str(name).strip(),
                price_tenge=price,
                old_price_tenge=old_price,
                in_stock=bool(item.get("CAN_BUY", item.get("CATALOG_AVAILABLE", True))),
                is_promoted=bool(old_price),
                store_url=f"{settings.galmart_base_url}{item.get('DETAIL_PAGE_URL', f'/catalog/detail/{sku}/')}",
                store_image_url=img_url or None,
                category_path=[cat_name],
                raw_json=item,
            )
        except Exception as e:
            logger.debug(f"Galmart parse error: {e}")
            return None

    async def _parse_html_page(self, url: str, cat_name: str, page_num: int) -> tuple[list[RawProduct], bool]:
        """HTML fallback — парсим страницу напрямую"""
        try:
            from parsel import Selector
            resp = await self._client.get(f"{url}?PAGEN_1={page_num}")
            sel = Selector(resp.text)

            products = []
            cards = sel.css(".product-item, .catalog-item, [class*='product']")

            for card in cards:
                name = card.css("*[class*='name']::text, h3::text, h2::text").get("").strip()
                price_raw = card.css("*[class*='price']:not([class*='old'])::text").get("")
                price = self.parse_price(price_raw)
                if not name or not price:
                    continue

                sku = card.attrib.get("data-id") or card.attrib.get("data-product-id") or name[:20]
                img = card.css("img::attr(src), img::attr(data-src)").get("")
                if img and not img.startswith("http"):
                    img = settings.galmart_base_url + img

                products.append(RawProduct(
                    store_slug="galmart",
                    store_sku=str(sku),
                    name_raw=name,
                    price_tenge=price,
                    in_stock=True,
                    store_url=f"{settings.galmart_base_url}/catalog/",
                    store_image_url=img or None,
                    category_path=[cat_name],
                ))

            # Есть ли следующая страница
            has_next = bool(sel.css(f"a[href*='PAGEN_1={page_num + 1}']"))
            return products, has_next

        except Exception as e:
            logger.error(f"Galmart HTML fallback error: {e}")
            return [], False

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        categories = await self._init_bitrix_session()
        if not categories:
            logger.error("Galmart: нет категорий!")
            return

        # Обновляем cookies в httpx клиенте
        self._client.cookies.update(self._session_cookies)

        total = 0
        logger.info(f"Galmart: {len(categories)} категорий")

        for cat in categories:
            cat_name = cat["name"]
            cat_url = cat["url"]
            page_num = 1
            logger.info(f"  [{cat_name}]")

            while True:
                products, has_next = await self._get_section_products(cat_url, cat_name, page_num)
                for p in products:
                    total += 1
                    yield p

                if not has_next or not products:
                    break
                page_num += 1
                await self._human_delay()

        logger.info(f"Galmart: итого {total} товаров")
