"""
Роутер умной корзины: принимает список product_ids,
возвращает оптимальную разбивку по магазинам (split-cart).
Использует SplitCartOptimizer из services/optimizer/optimizer.py.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.deps import get_db, get_current_user_optional
from services.optimizer.optimizer import SplitCartOptimizer, CartItem

router = APIRouter()
logger = logging.getLogger("api.cart")


# ── Request / Response schemas ────────────────────────────────

class CartItemIn(BaseModel):
    product_id: UUID
    quantity: float = Field(default=1.0, gt=0, le=100)


class CartOptimizeRequest(BaseModel):
    product_ids: list[UUID] = Field(..., min_length=1, max_length=50)


class CartItemOut(BaseModel):
    product_id: UUID
    canonical_name: str
    quantity: float
    unit_price: float
    total_price: float
    store_slug: str
    store_url: Optional[str] = None
    image_url: Optional[str] = None


class StoreAssignmentOut(BaseModel):
    store_id: UUID
    store_slug: str
    store_name: str
    items: list[CartItemOut]
    items_subtotal: float
    delivery_cost: float
    total: float


class CartOptimizeResponse(BaseModel):
    assignments: list[StoreAssignmentOut]
    grand_total: float
    baseline_total: float
    savings: float
    savings_pct: float
    strategy: str
    not_found: list[str]


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/optimize", response_model=CartOptimizeResponse)
async def optimize_cart(
    req: CartOptimizeRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_optional),
):
    """
    Оптимизация корзины: принимает список product_ids,
    находит canonical_name каждого товара из БД и возвращает
    оптимальное распределение покупок по магазинам.
    """
    # Resolve product names from DB
    rows = (await session.execute(text("""
        SELECT id, canonical_name
        FROM products
        WHERE id = ANY(:ids)
    """), {"ids": list(req.product_ids)})).fetchall()

    found_map = {r.id: r.canonical_name for r in rows}
    missing_ids = [str(pid) for pid in req.product_ids if pid not in found_map]

    if not found_map:
        raise HTTPException(status_code=400, detail="Ни один товар не найден в базе")

    cart_items = [
        CartItem(
            product_id=pid,
            quantity=Decimal("1"),
            canonical_name=name,
        )
        for pid, name in found_map.items()
    ]

    try:
        optimizer = SplitCartOptimizer(session)
        result = await optimizer.optimize(cart_items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    assignments_out = []
    for a in result.assignments:
        assignments_out.append(StoreAssignmentOut(
            store_id=a.store_id,
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
                    image_url=i.image_url,
                )
                for i in a.items
            ],
            items_subtotal=float(a.items_subtotal),
            delivery_cost=float(a.delivery_cost),
            total=float(a.total),
        ))

    not_found = result.not_found_products
    if missing_ids:
        not_found.extend([f"id:{mid}" for mid in missing_ids])

    return CartOptimizeResponse(
        assignments=assignments_out,
        grand_total=float(result.grand_total),
        baseline_total=float(result.baseline_single_store_total),
        savings=float(result.savings),
        savings_pct=result.savings_pct,
        strategy=result.strategy,
        not_found=not_found,
    )
