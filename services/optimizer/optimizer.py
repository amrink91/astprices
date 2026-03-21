"""
Алгоритм оптимизации корзины.
Перебор 2^5-1=31 комбинации магазинов. Учёт доставки.
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Store

logger = logging.getLogger("optimizer")


@dataclass
class CartItem:
    product_id: UUID
    quantity: Decimal
    canonical_name: str


@dataclass
class CartItemResult:
    product_id: UUID
    canonical_name: str
    quantity: Decimal
    unit_price: Decimal
    total_price: Decimal
    store_slug: str
    store_url: Optional[str] = None
    image_url: Optional[str] = None


@dataclass
class StoreAssignment:
    store_id: UUID
    store_slug: str
    store_name: str
    items: list[CartItemResult]
    items_subtotal: Decimal
    delivery_cost: Decimal
    total: Decimal
    checkout_url: Optional[str] = None


@dataclass
class OptimizationResult:
    assignments: list[StoreAssignment]
    grand_total: Decimal
    baseline_single_store_total: Decimal
    savings: Decimal
    savings_pct: float
    strategy: str  # "single_store" | "split_2" | "split_3"
    not_found_products: list[str] = field(default_factory=list)


class SplitCartOptimizer:
    MAX_STORES = 3  # максимум магазинов в сплите

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def optimize(self, cart_items: list[CartItem]) -> OptimizationResult:
        price_matrix, stores_info = await self._build_price_matrix(cart_items)

        not_found = [i.canonical_name for i in cart_items if i.product_id not in price_matrix]
        found_items = [i for i in cart_items if i.product_id in price_matrix]

        if not found_items:
            raise ValueError("Ни один товар не найден в магазинах")

        available = self._stores_with_coverage(found_items, price_matrix, min_coverage=0.6)
        if not available:
            raise ValueError("Нет магазинов с достаточным ассортиментом")

        best: Optional[OptimizationResult] = None
        all_results = []

        for n in range(1, min(self.MAX_STORES + 1, len(available) + 1)):
            for combo in itertools.combinations(available, n):
                r = self._eval(found_items, combo, price_matrix, stores_info)
                if r:
                    all_results.append(r)
                    if best is None or r.grand_total < best.grand_total:
                        best = r

        if not best:
            raise ValueError("Не удалось построить корзину")

        single = min(
            (r for r in all_results if len(r.assignments) == 1),
            key=lambda r: r.grand_total,
            default=best,
        )
        best.baseline_single_store_total = single.grand_total
        best.savings = single.grand_total - best.grand_total
        best.savings_pct = round(float(best.savings / single.grand_total * 100), 1) if single.grand_total > 0 else 0.0
        best.strategy = "single_store" if len(best.assignments) == 1 else f"split_{len(best.assignments)}"
        best.not_found_products = not_found
        return best

    def _eval(self, items, store_combo, price_matrix, stores_info) -> Optional[OptimizationResult]:
        store_items: dict[str, list] = {s: [] for s in store_combo}

        for item in items:
            available_in_combo = {
                s: price_matrix[item.product_id][s]
                for s in store_combo
                if s in price_matrix.get(item.product_id, {})
                and price_matrix[item.product_id][s]["in_stock"]
            }
            if not available_in_combo:
                # Ищем в любом доступном магазине
                all_av = {s: d for s, d in price_matrix.get(item.product_id, {}).items() if d["in_stock"]}
                if not all_av:
                    continue
                best_s = min(all_av, key=lambda s: all_av[s]["price"])
                available_in_combo = {best_s: all_av[best_s]}
                if best_s not in store_items:
                    store_items[best_s] = []

            best_store = min(available_in_combo, key=lambda s: available_in_combo[s]["price"])
            sd = available_in_combo[best_store]
            total_price = sd["price"] * item.quantity

            store_items[best_store].append(CartItemResult(
                product_id=item.product_id,
                canonical_name=item.canonical_name,
                quantity=item.quantity,
                unit_price=sd["price"],
                total_price=total_price,
                store_slug=best_store,
                store_url=sd.get("store_url"),
                image_url=sd.get("image_url"),
            ))

        assignments = []
        grand_total = Decimal("0")

        for store_slug, its in store_items.items():
            if not its:
                continue
            si = stores_info[store_slug]
            subtotal = sum(i.total_price for i in its)

            if subtotal < si["min_order"]:
                return None  # нарушение min_order → невалидная комбинация

            delivery = Decimal("0") if subtotal >= si["free_threshold"] else si["delivery_cost"]
            total = subtotal + delivery
            grand_total += total

            assignments.append(StoreAssignment(
                store_id=si["id"],
                store_slug=store_slug,
                store_name=si["name"],
                items=its,
                items_subtotal=subtotal,
                delivery_cost=delivery,
                total=total,
            ))

        if not assignments:
            return None

        return OptimizationResult(
            assignments=assignments,
            grand_total=grand_total,
            baseline_single_store_total=Decimal("0"),
            savings=Decimal("0"),
            savings_pct=0.0,
            strategy="",
        )

    def _stores_with_coverage(self, items, price_matrix, min_coverage=0.6) -> list[str]:
        all_stores: set[str] = set()
        for pp in price_matrix.values():
            all_stores.update(pp.keys())

        return [
            s for s in all_stores
            if sum(
                1 for i in items
                if s in price_matrix.get(i.product_id, {})
                and price_matrix[i.product_id][s]["in_stock"]
            ) / len(items) >= min_coverage
        ]

    async def _build_price_matrix(self, cart_items: list[CartItem]) -> tuple[dict, dict]:
        product_ids = [i.product_id for i in cart_items]

        rows = (await self.session.execute(text("""
            SELECT product_id, store_slug, store_id, price_tenge,
                   store_url, store_image_url, in_stock
            FROM current_prices
            WHERE product_id = ANY(:ids) AND in_stock = true
        """), {"ids": product_ids})).fetchall()

        price_matrix: dict = {}
        for r in rows:
            price_matrix.setdefault(r.product_id, {})[r.store_slug] = {
                "price": r.price_tenge,
                "store_url": r.store_url,
                "image_url": r.store_image_url,
                "in_stock": r.in_stock,
            }

        stores = (await self.session.execute(
            select(Store).where(Store.is_active == True)
        )).scalars().all()

        stores_info = {
            s.slug: {
                "id": s.id, "name": s.display_name,
                "delivery_cost": s.delivery_cost_tenge,
                "free_threshold": s.delivery_free_threshold,
                "min_order": s.min_order_tenge,
            }
            for s in stores
        }
        return price_matrix, stores_info

    async def get_best_split_for_categories(self, category_slugs: list[str]) -> Optional[OptimizationResult]:
        rows = (await self.session.execute(text("""
            SELECT DISTINCT ON (p.category_id)
                p.id AS product_id, p.canonical_name
            FROM products p
            JOIN categories c ON c.id = p.category_id
            JOIN current_prices cp ON cp.product_id = p.id
            WHERE c.slug = ANY(:slugs) AND cp.in_stock = true
            ORDER BY p.category_id, cp.price_tenge ASC
            LIMIT 15
        """), {"slugs": category_slugs})).fetchall()

        if not rows:
            return None

        cart_items = [CartItem(product_id=r.product_id, quantity=Decimal("1"), canonical_name=r.canonical_name) for r in rows]
        try:
            return await self.optimize(cart_items)
        except Exception as e:
            logger.error(f"Ошибка оптимизации: {e}")
            return None
