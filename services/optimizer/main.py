"""Optimizer microservice — FastAPI wrapper around SplitCartOptimizer."""
import logging
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.config import settings
from shared.db import get_session
from services.optimizer.optimizer import SplitCartOptimizer, CartItem

logging.basicConfig(level=settings.log_level, format="%(asctime)s  %(name)-25s %(levelname)-8s  %(message)s")

app = FastAPI(title="Astana Prices — Optimizer", docs_url="/docs", redoc_url=None)


class OptimizeRequest(BaseModel):
    product_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    quantities: list[float] = Field(default=None)


class ItemOut(BaseModel):
    product_id: UUID
    canonical_name: str
    quantity: float
    unit_price: float
    total_price: float
    store_slug: str
    store_url: str | None = None
    image_url: str | None = None


class StoreAssignmentOut(BaseModel):
    store_slug: str
    store_name: str
    items: list[ItemOut]
    items_subtotal: float
    delivery_cost: float
    total: float


class OptimizeResponse(BaseModel):
    assignments: list[StoreAssignmentOut]
    grand_total: float
    baseline_single_store_total: float
    savings: float
    savings_pct: float
    strategy: str
    not_found_products: list[str]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/optimize", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest):
    quantities = req.quantities or [1.0] * len(req.product_ids)
    if len(quantities) != len(req.product_ids):
        raise HTTPException(400, "quantities length must match product_ids")

    async with get_session() as session:
        # resolve product names
        from sqlalchemy import text
        rows = (await session.execute(
            text("SELECT id, canonical_name FROM products WHERE id = ANY(:ids)"),
            {"ids": list(req.product_ids)},
        )).fetchall()
        name_map = {r.id: r.canonical_name for r in rows}

        cart_items = []
        for pid, qty in zip(req.product_ids, quantities):
            name = name_map.get(pid, str(pid))
            cart_items.append(CartItem(product_id=pid, quantity=Decimal(str(qty)), canonical_name=name))

        try:
            optimizer = SplitCartOptimizer(session)
            result = optimizer.optimize(cart_items) if not cart_items else await optimizer.optimize(cart_items)
        except ValueError as e:
            raise HTTPException(400, str(e))

    return OptimizeResponse(
        assignments=[
            StoreAssignmentOut(
                store_slug=a.store_slug,
                store_name=a.store_name,
                items=[
                    ItemOut(
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
            )
            for a in result.assignments
        ],
        grand_total=float(result.grand_total),
        baseline_single_store_total=float(result.baseline_single_store_total),
        savings=float(result.savings),
        savings_pct=result.savings_pct,
        strategy=result.strategy,
        not_found_products=result.not_found_products,
    )
