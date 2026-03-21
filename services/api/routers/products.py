"""
Роутер продуктов: поиск, сравнение, история цен.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.deps import get_db

router = APIRouter()
logger = logging.getLogger("api.products")


# ── Схемы ──────────────────────────────────────────────────────

class PricePoint(BaseModel):
    store_name: str
    store_slug: str
    price_tenge: float
    old_price_tenge: Optional[float]
    discount_pct: Optional[float]
    in_stock: bool
    is_promoted: bool
    store_url: Optional[str]
    store_image_url: Optional[str]


class ProductDetail(BaseModel):
    id: UUID
    canonical_name: str
    brand: Optional[str]
    unit: Optional[str]
    unit_size: Optional[float]
    category_slug: Optional[str]
    category_name: Optional[str]
    category_emoji: Optional[str]
    prices: list[PricePoint]
    min_price: Optional[float]
    max_price: Optional[float]


class ProductListItem(BaseModel):
    id: UUID
    canonical_name: str
    brand: Optional[str]
    category_emoji: Optional[str]
    min_price: Optional[float]
    best_store: Optional[str]
    discount_pct: Optional[float]
    in_stock: bool


class PriceHistoryPoint(BaseModel):
    recorded_at: str
    price_tenge: float
    store_name: str


# ── Endpoints ──────────────────────────────────────────────────

@router.get("", response_model=list[ProductListItem])
async def list_products(
    category: Optional[str] = Query(None, description="Slug категории"),
    search: Optional[str] = Query(None, description="Поисковый запрос"),
    store: Optional[str] = Query(None, description="Slug магазина"),
    promoted: Optional[bool] = Query(None, description="Только акции"),
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    """Список товаров с минимальными ценами."""
    conditions = ["cp.in_stock = true"]
    params: dict = {"limit": limit, "offset": offset}

    if category:
        conditions.append("c.slug = :category")
        params["category"] = category
    if store:
        conditions.append("s.slug = :store")
        params["store"] = store
    if promoted:
        conditions.append("cp.is_promoted = true")
    if search:
        conditions.append("p.canonical_name ILIKE :search")
        params["search"] = f"%{search}%"

    where = " AND ".join(conditions)

    rows = (await session.execute(text(f"""
        SELECT DISTINCT ON (p.id)
            p.id,
            p.canonical_name,
            p.brand,
            COALESCE(c.icon_emoji, '🛒') AS emoji,
            cp.price_tenge              AS min_price,
            s.display_name              AS best_store,
            cp.discount_pct,
            cp.in_stock
        FROM current_prices cp
        JOIN products p     ON p.id = cp.product_id
        JOIN stores s       ON s.id = cp.store_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE {where}
        ORDER BY p.id, cp.price_tenge ASC
        LIMIT :limit OFFSET :offset
    """), params)).fetchall()

    return [
        ProductListItem(
            id=r.id,
            canonical_name=r.canonical_name,
            brand=r.brand,
            category_emoji=r.emoji,
            min_price=float(r.min_price) if r.min_price else None,
            best_store=r.best_store,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            in_stock=r.in_stock,
        )
        for r in rows
    ]


@router.get("/search", response_model=list[ProductListItem])
async def search_products(
    q: str = Query(..., min_length=2, description="Поисковый запрос"),
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
):
    """Полнотекстовый поиск по каноническому названию (pg_trgm)."""
    rows = (await session.execute(text("""
        SELECT DISTINCT ON (p.id)
            p.id,
            p.canonical_name,
            p.brand,
            COALESCE(c.icon_emoji, '🛒') AS emoji,
            cp.price_tenge              AS min_price,
            s.display_name              AS best_store,
            cp.discount_pct,
            cp.in_stock,
            similarity(p.canonical_name, :q) AS sim
        FROM products p
        JOIN current_prices cp ON cp.product_id = p.id
        JOIN stores s          ON s.id = cp.store_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.canonical_name % :q
          AND cp.in_stock = true
        ORDER BY p.id, sim DESC, cp.price_tenge ASC
        LIMIT :limit
    """), {"q": q, "limit": limit})).fetchall()

    return [
        ProductListItem(
            id=r.id,
            canonical_name=r.canonical_name,
            brand=r.brand,
            category_emoji=r.emoji,
            min_price=float(r.min_price) if r.min_price else None,
            best_store=r.best_store,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            in_stock=r.in_stock,
        )
        for r in rows
    ]


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(
    product_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """Детали товара: все цены по магазинам."""
    rows = (await session.execute(text("""
        SELECT
            p.id, p.canonical_name, p.brand, p.unit,
            p.unit_size::float,
            c.slug   AS category_slug,
            c.name_ru AS category_name,
            COALESCE(c.icon_emoji, '🛒') AS emoji,
            s.display_name AS store_name,
            s.slug         AS store_slug,
            cp.price_tenge,
            cp.old_price_tenge,
            cp.discount_pct,
            cp.in_stock,
            cp.is_promoted,
            cp.store_url,
            cp.store_image_url
        FROM current_prices cp
        JOIN products p    ON p.id = cp.product_id
        JOIN stores s      ON s.id = cp.store_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.id = :pid
        ORDER BY cp.price_tenge ASC
    """), {"pid": product_id})).fetchall()

    if not rows:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Товар не найден")

    r0 = rows[0]
    prices = [
        PricePoint(
            store_name=r.store_name,
            store_slug=r.store_slug,
            price_tenge=float(r.price_tenge),
            old_price_tenge=float(r.old_price_tenge) if r.old_price_tenge else None,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            in_stock=r.in_stock,
            is_promoted=r.is_promoted,
            store_url=r.store_url,
            store_image_url=r.store_image_url,
        )
        for r in rows
    ]
    all_prices = [float(r.price_tenge) for r in rows if r.in_stock]

    return ProductDetail(
        id=r0.id,
        canonical_name=r0.canonical_name,
        brand=r0.brand,
        unit=r0.unit,
        unit_size=r0.unit_size,
        category_slug=r0.category_slug,
        category_name=r0.category_name,
        category_emoji=r0.emoji,
        prices=prices,
        min_price=min(all_prices) if all_prices else None,
        max_price=max(all_prices) if all_prices else None,
    )


@router.get("/{product_id}/history", response_model=list[PriceHistoryPoint])
async def price_history(
    product_id: UUID,
    days: int = Query(30, ge=1, le=365),
    store: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_db),
):
    """История цен товара (для графика)."""
    params: dict = {"pid": product_id, "days": days}
    store_filter = ""
    if store:
        store_filter = "AND s.slug = :store"
        params["store"] = store

    rows = (await session.execute(text(f"""
        SELECT
            ph.recorded_at::text,
            ph.price_tenge,
            s.display_name AS store_name
        FROM price_history ph
        JOIN store_products sp ON sp.id = ph.store_product_id
        JOIN products p        ON p.id = sp.product_id
        JOIN stores s          ON s.id = sp.store_id
        WHERE p.id = :pid
          AND ph.recorded_at >= NOW() - make_interval(days => :days)
          {store_filter}
        ORDER BY ph.recorded_at ASC
        LIMIT 2000
    """), params)).fetchall()

    return [
        PriceHistoryPoint(
            recorded_at=r.recorded_at,
            price_tenge=float(r.price_tenge),
            store_name=r.store_name,
        )
        for r in rows
    ]
