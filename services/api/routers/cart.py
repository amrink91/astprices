"""
Роутер умной корзины: оптимизация + генерация URL для магазинов.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.deps import get_db, get_current_user_optional
from services.optimizer.optimizer import SplitCartOptimizer, CartItem

router = APIRouter()
logger = logging.getLogger("api.cart")


# ── Схемы ──────────────────────────────────────────────────────

class CartItemIn(BaseModel):
    product_id: UUID
    quantity: float = 1.0
    canonical_name: str


class CartRequest(BaseModel):
    items: list[CartItemIn]
    max_stores: int = 3


class CartItemOut(BaseModel):
    product_id: UUID
    canonical_name: str
    quantity: float
    unit_price: float
    total_price: float
    store_slug: str
    store_url: Optional[str]


class StoreAssignmentOut(BaseModel):
    store_slug: str
    store_name: str
    items: list[CartItemOut]
    items_subtotal: float
    delivery_cost: float
    total: float
    checkout_url: Optional[str]


class CartResponse(BaseModel):
    assignments: list[StoreAssignmentOut]
    grand_total: float
    baseline_total: float
    savings: float
    savings_pct: float
    strategy: str
    not_found: list[str]


# ── Endpoints ──────────────────────────────────────────────────

@router.post("/optimize", response_model=CartResponse)
async def optimize_cart(
    req: CartRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_optional),
):
    """
    Оптимизация корзины: разбивка по магазинам для минимальной цены.
    Авторизация не обязательна.
    """
    cart_items = [
        CartItem(
            product_id=i.product_id,
            quantity=Decimal(str(i.quantity)),
            canonical_name=i.canonical_name,
        )
        for i in req.items
    ]

    try:
        opt = SplitCartOptimizer(session)
        result = await opt.optimize(cart_items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Генерируем checkout URL для каждого магазина
    from services.checkout.cart_url_builder import build_cart_url

    assignments_out = []
    for a in result.assignments:
        checkout_items = [
            {"store_sku": i.store_url or "", "store_url": i.store_url, "name": i.canonical_name, "quantity": int(i.quantity)}
            for i in a.items
        ]
        checkout_url = build_cart_url(a.store_slug, checkout_items)

        assignments_out.append(StoreAssignmentOut(
            store_slug=a.store_slug,
            store_name=a.store_name,
            items=[
                CartItemOut(
                    product_id=i.product_id,
                    canonical_name=i.canonical_name,
                    quantity=float(i.quantity),
                    unit_price=float(i.unit_price),
                    total_price=float(i.total_price),
                    store_slug=i.store_slug,
                    store_url=i.store_url,
                )
                for i in a.items
            ],
            items_subtotal=float(a.items_subtotal),
            delivery_cost=float(a.delivery_cost),
            total=float(a.total),
            checkout_url=checkout_url,
        ))

    return CartResponse(
        assignments=assignments_out,
        grand_total=float(result.grand_total),
        baseline_total=float(result.baseline_single_store_total),
        savings=float(result.savings),
        savings_pct=result.savings_pct,
        strategy=result.strategy,
        not_found=result.not_found_products,
    )


@router.post("/checkout-urls")
async def checkout_urls(
    assignments: list[StoreAssignmentOut],
):
    """
    Сгенерировать прямые URL для добавления товаров в корзину каждого магазина.
    """
    from services.checkout.cart_url_builder import build_cart_url

    result = {}
    for a in assignments:
        checkout_items = [
            {"store_sku": item.store_url or "", "store_url": item.store_url,
             "name": item.canonical_name, "quantity": int(item.quantity)}
            for item in a.items
        ]
        url = build_cart_url(a.store_slug, checkout_items)
        result[a.store_slug] = url

    return result
