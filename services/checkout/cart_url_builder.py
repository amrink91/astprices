"""
Генерация ссылок-корзин для магазинов.
⚠️ URL форматы нужна верификация через browser devtools!
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from shared.config import settings

logger = logging.getLogger("checkout")


@dataclass
class CartLink:
    store_slug: str
    store_name: str
    url: str
    fallback_urls: list[str]  # ссылки на товары если deeplink не работает
    method: str  # deeplink | product_list | manual


class CartURLBuilder:

    def build(self, store_slug: str, items: list[dict]) -> CartLink:
        """items: [{store_sku, store_url, name, quantity}]"""
        builders = {
            "magnum":  self._magnum,
            "arbuz":   self._arbuz,
            "small":   self._small,
            "galmart": self._galmart,
            "astore":  self._astore,
            "anvar":   self._anvar,
        }
        return builders.get(store_slug, self._generic)(store_slug, items)

    def _magnum(self, slug, items) -> CartLink:
        # ⚠️ Формат нужна верификация! Проверь через devtools magnum.kz
        items_param = ",".join(f"{i['store_sku']}:{i['quantity']}" for i in items)
        url = f"{settings.magnum_base_url}/cart?add={items_param}"
        return CartLink(slug, "Magnum", url, [i["store_url"] for i in items if i.get("store_url")], "deeplink")

    def _arbuz(self, slug, items) -> CartLink:
        # ⚠️ Формат нужна верификация!
        params = []
        for i in items:
            params.append(("add[]", i["store_sku"]))
            params.append((f"qty[{i['store_sku']}]", str(i["quantity"])))
        url = f"{settings.arbuz_base_url}/ru/astana/basket?{urlencode(params)}"
        fallback = [f"{settings.arbuz_base_url}/ru/astana/product/{i['store_sku']}" for i in items]
        return CartLink(slug, "Arbuz.kz", url, fallback, "deeplink")

    def _small(self, slug, items) -> CartLink:
        items_str = ",".join(f"{i['store_sku']}:{i['quantity']}" for i in items)
        url = f"{settings.small_base_url}/cart?items={items_str}"
        return CartLink(slug, "Small", url, [i["store_url"] for i in items if i.get("store_url")], "deeplink")

    def _galmart(self, slug, items) -> CartLink:
        # Bitrix — нет прямого deeplink в корзину
        fallback = [i["store_url"] for i in items if i.get("store_url")]
        return CartLink(slug, "Galmart", fallback[0] if fallback else settings.galmart_base_url, fallback, "product_list")

    def _astore(self, slug, items) -> CartLink:
        items_str = ",".join(f"{i['store_sku']}:{i['quantity']}" for i in items)
        url = f"{settings.astore_base_url}/cart?add={items_str}"
        return CartLink(slug, "A-Store", url, [i["store_url"] for i in items if i.get("store_url")], "deeplink")

    def _generic(self, slug, items) -> CartLink:
        fallback = [i["store_url"] for i in items if i.get("store_url")]
        return CartLink(slug, slug.capitalize(), fallback[0] if fallback else "#", fallback, "manual")

    def _anvar(self, slug, items) -> CartLink:
        items_str = ",".join(f"{i['store_sku']}:{i['quantity']}" for i in items)
        url = f"{settings.anvar_base_url}/cart?add={items_str}"
        return CartLink(slug, "Анвар", url, [i["store_url"] for i in items if i.get("store_url")], "deeplink")

    def generate_checklist_text(self, assignments: list) -> str:
        """Текстовый чеклист для офлайн-похода в магазин"""
        lines = ["🛒 Список покупок — Астана\n"]
        for a in assignments:
            lines.append(f"\n🏪 {a.store_name}:")
            for item in a.items:
                lines.append(f"  □ {item.canonical_name} × {item.quantity}  —  {item.total_price:.0f}₸")
            delivery_str = "Бесплатно" if a.delivery_cost == 0 else f"{a.delivery_cost:.0f}₸"
            lines.append(f"  Товары: {a.items_subtotal:.0f}₸ | Доставка: {delivery_str}")
        total = sum(a.total for a in assignments)
        lines.append(f"\n💰 ИТОГО: {total:.0f}₸")
        return "\n".join(lines)


# ── Module-level convenience ──────────────────────────────────

_builder = CartURLBuilder()


def build_cart_url(store_slug: str, items: list[dict]) -> Optional[str]:
    """
    Обёртка: принимает store_slug и список [{store_sku, store_url, name, quantity}].
    Возвращает URL строку (или None если deeplink не доступен).
    """
    try:
        link = _builder.build(store_slug, items)
        return link.url
    except Exception:
        return None
