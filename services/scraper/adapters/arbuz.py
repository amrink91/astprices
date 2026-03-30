"""Парсер Arbuz.kz — Playwright HTML scraping с обходом подкатегорий"""
from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.scrapers.base import AbstractStoreScraper, RawProduct

# Все категории и подкатегории Arbuz Астана — (ID, slug, name)
CATEGORIES_WITH_SUBS = {
    "Молоко, сыр и яйца": [
        (19986, "moloko_slivki_sgush_nnoe_moloko", "Молоко, сливки, сгущённое молоко"),
        (225446, "kefir_tvorog_smetana", "Кефир, творог, сметана"),
        (225171, "iogurty_syrki_deserty", "Йогурты, сырки, десерты"),
        (225245, "yaica_maslo_margarin", "Яйца, масло, маргарин"),
        (20160, "syr", "Сыр"),
    ],
    "Хлеб и выпечка": [
        (225162, "hleb_i_vypechka", "Хлеб и выпечка"),
    ],
    "Овощи, фрукты и ягоды": [
        (225163, "ovoschi_frukty_i_yagody", "Овощи, фрукты и ягоды"),
    ],
    "Мясо, птица и колбасы": [
        (19907, "myaso_steiki_farsh", "Мясо, стейки, фарш"),
        (225173, "kurica_indeika_i_ptica", "Курица, индейка и птица"),
        (225609, "polufabrikaty_i_marinady", "Полуфабрикаты и маринады"),
        (19855, "kolbasy", "Колбасы"),
        (225180, "sosiski_sardelki", "Сосиски, сардельки"),
        (225451, "myasnye_delikatesy", "Мясные деликатесы"),
    ],
    "Рыба и морепродукты": [
        (225165, "ryba_i_moreprodukty", "Рыба и морепродукты"),
    ],
    "Замороженные продукты": [
        (225167, "zamorozhennye_produkty", "Замороженные продукты"),
    ],
    "Бакалея": [
        (225168, "bakaleya", "Бакалея"),
    ],
    "Напитки": [
        (20697, "voda", "Вода"),
        (20784, "gazirovka_i_energetiki", "Газировка и энергетики"),
        (184573, "holodnyj_chaj_kompot_mors", "Холодный чай, компот, морс"),
        (20739, "soki_i_nektary", "Соки и нектары"),
    ],
    "Сладости и снеки": [
        (225170, "sladosti_i_sneki", "Сладости и снеки"),
    ],
    "Чай, кофе и какао": [
        (225171, "chay_kofe_i_kakao", "Чай, кофе и какао"),
    ],
    "Соусы и приправы": [
        (225172, "sousy_i_pripravy", "Соусы и приправы"),
    ],
    "Детское питание": [
        (225173, "detskoe_pitanie", "Детское питание"),
    ],
    "Здоровое питание": [
        (225175, "zdorovoe_pitanie", "Здоровое питание"),
    ],
}


class ArbuzScraper(AbstractStoreScraper):
    CITY = "astana"

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
        if hasattr(self, '_pw') and self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        await super().close()

    def _parse_price(self, text: str) -> Optional[Decimal]:
        """Извлекаем цену из текста вроде '435₸' или '8 304₸'"""
        digits = re.sub(r'[^\d]', '', text.split('₸')[0].strip())
        if digits:
            return Decimal(digits)
        return None

    async def _parse_cards(self, cat_name: str) -> list[RawProduct]:
        """Парсим карточки товаров на текущей странице"""
        products = []
        cards = await self._page.query_selector_all("article.product-card")

        for card in cards:
            try:
                link = await card.query_selector("a")
                if not link:
                    continue

                title = await link.get_attribute("title") or ""
                href = await link.get_attribute("href") or ""
                if not title:
                    continue

                sku_match = re.search(r'/item/(\d+)', href)
                sku = sku_match.group(1) if sku_match else ""
                if not sku:
                    continue

                text = await card.text_content() or ""
                price_matches = re.findall(r'([\d\s]+)₸', text)
                if not price_matches:
                    continue

                price = self._parse_price(price_matches[-1] + '₸')
                if not price or price <= 0:
                    continue

                old_price = None
                if len(price_matches) >= 2:
                    old_p = self._parse_price(price_matches[0] + '₸')
                    if old_p and old_p > price:
                        old_price = old_p

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

        return products

    async def _scrape_single_page(self, cat_id: int, cat_slug: str, cat_name: str) -> list[RawProduct]:
        """Скрапим одну страницу категории/подкатегории"""
        url = f"https://arbuz.kz/ru/{self.CITY}/catalog/cat/{cat_id}-{cat_slug}"
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._page.wait_for_timeout(3000)

            for _ in range(5):
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self._page.wait_for_timeout(800)

            products = await self._parse_cards(cat_name)
            self.logger.info(f"    [{cat_name}] {len(products)} товаров")
            return products
        except Exception as e:
            self.logger.error(f"Page {cat_name} error: {e}")
            return []

    async def scrape_all_products(self) -> AsyncIterator[RawProduct]:
        await self._init_browser()

        self.logger.info(f"Arbuz: {len(CATEGORIES_WITH_SUBS)} категорий")
        total = 0
        seen_skus = set()

        for group_name, subcats in CATEGORIES_WITH_SUBS.items():
            self.logger.info(f"  [{group_name}] {len(subcats)} подкатегорий")
            products = []
            for cat_id, cat_slug, cat_name in subcats:
                sub_products = await self._scrape_single_page(cat_id, cat_slug, cat_name)
                products.extend(sub_products)
                await asyncio.sleep(0.5)

            for p in products:
                if p.store_sku not in seen_skus:
                    seen_skus.add(p.store_sku)
                    total += 1
                    yield p

            await asyncio.sleep(1)

        self.logger.info(f"Arbuz: итого {total} товаров")
