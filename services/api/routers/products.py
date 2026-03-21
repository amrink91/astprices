"""
Роутер продуктов: список с пагинацией, фильтрация, поиск, детали, история цен.
Все запросы идут через materialized view current_prices.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.deps import get_db

router = APIRouter()
logger = logging.getLogger("api.products")


# ── Response schemas ──────────────────────────────────────────

class PricePoint(BaseModel):
    store_name: str
    store_slug: str
    price_tenge: float
    old_price_tenge: Optional[float] = None
    discount_pct: Optional[float] = None
    in_stock: bool
    is_promoted: bool
    store_url: Optional[str] = None
    store_image_url: Optional[str] = None


class ProductListItem(BaseModel):
    id: UUID
    canonical_name: str
    brand: Optional[str] = None
    category_emoji: Optional[str] = None
    min_price: Optional[float] = None
    best_store: Optional[str] = None
    discount_pct: Optional[float] = None
    in_stock: bool


class PaginatedProducts(BaseModel):
    items: list[ProductListItem]
    total: int
    limit: int
    offset: int


class ProductDetail(BaseModel):
    id: UUID
    canonical_name: str
    brand: Optional[str] = None
    unit: Optional[str] = None
    unit_size: Optional[float] = None
    image_url: Optional[str] = None
    category_slug: Optional[str] = None
    category_name: Optional[str] = None
    category_emoji: Optional[str] = None
    prices: list[PricePoint]
    min_price: Optional[float] = None
    max_price: Optional[float] = None


class PriceHistoryPoint(BaseModel):
    recorded_at: str
    price_tenge: float
    store_name: str
    store_slug: str


# ── Endpoints ─────────────────────────────────────────────────

@router.get("", response_model=PaginatedProducts)
async def list_products(
    category: Optional[str] = Query(None, description="Slug категории для фильтрации"),
    search: Optional[str] = Query(None, min_length=2, description="Поиск по названию товара"),
    store: Optional[str] = Query(None, description="Slug магазина"),
    promoted: Optional[bool] = Query(None, description="Только акционные товары"),
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    """
    Список товаров с минимальными ценами из current_prices.

    Поддерживает пагинацию (limit/offset), фильтрацию по категории,
    магазину, акциям и поиск по названию (ILIKE).
    """
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

    # Total count for pagination
    count_row = (await session.execute(text(f"""
        SELECT COUNT(DISTINCT p.id)
        FROM current_prices cp
        JOIN products p      ON p.id = cp.product_id
        JOIN stores s        ON s.id = cp.store_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE {where}
    """), params)).scalar_one()

    # Fetch page of products with best price per product
    rows = (await session.execute(text(f"""
        SELECT DISTINCT ON (p.id)
            p.id,
            p.canonical_name,
            p.brand,
            COALESCE(c.icon_emoji, '') AS emoji,
            cp.price_tenge             AS min_price,
            s.display_name             AS best_store,
            cp.discount_pct,
            cp.in_stock
        FROM current_prices cp
        JOIN products p      ON p.id = cp.product_id
        JOIN stores s        ON s.id = cp.store_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE {where}
        ORDER BY p.id, cp.price_tenge ASC
        LIMIT :limit OFFSET :offset
    """), params)).fetchall()

    items = [
        ProductListItem(
            id=r.id,
            canonical_name=r.canonical_name,
            brand=r.brand,
            category_emoji=r.emoji or None,
            min_price=float(r.min_price) if r.min_price else None,
            best_store=r.best_store,
            discount_pct=float(r.discount_pct) if r.discount_pct else None,
            in_stock=r.in_stock,
        )
        for r in rows
    ]

    return PaginatedProducts(items=items, total=count_row, limit=limit, offset=offset)


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(
    product_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """Детальная информация о товаре: цены из всех магазинов."""
    rows = (await session.execute(text("""
        SELECT
            p.id, p.canonical_name, p.brand, p.unit,
            p.unit_size::float, p.image_url,
            c.slug          AS category_slug,
            c.name_ru       AS category_name,
            COALESCE(c.icon_emoji, '') AS emoji,
            s.display_name  AS store_name,
            s.slug          AS store_slug,
            cp.price_tenge,
            cp.old_price_tenge,
            cp.discount_pct,
            cp.in_stock,
            cp.is_promoted,
            cp.store_url,
            cp.store_image_url
        FROM current_prices cp
        JOIN products p      ON p.id = cp.product_id
        JOIN stores s        ON s.id = cp.store_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.id = :pid
        ORDER BY cp.price_tenge ASC
    """), {"pid": product_id})).fetchall()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар не найден",
        )

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
    in_stock_prices = [float(r.price_tenge) for r in rows if r.in_stock]

    return ProductDetail(
        id=r0.id,
        canonical_name=r0.canonical_name,
        brand=r0.brand,
        unit=r0.unit,
        unit_size=r0.unit_size,
        image_url=r0.image_url,
        category_slug=r0.category_slug,
        category_name=r0.category_name,
        category_emoji=r0.emoji or None,
        prices=prices,
        min_price=min(in_stock_prices) if in_stock_prices else None,
        max_price=max(in_stock_prices) if in_stock_prices else None,
    )


@router.get("/{product_id}/history", response_model=list[PriceHistoryPoint])
async def price_history(
    product_id: UUID,
    days: int = Query(30, ge=1, le=365, description="Глубина истории в днях"),
    store: Optional[str] = Query(None, description="Slug магазина для фильтрации"),
    session: AsyncSession = Depends(get_db),
):
    """История цен товара по всем магазинам (или конкретному)."""
    params: dict = {"pid": product_id, "days": days}
    store_filter = ""
    if store:
        store_filter = "AND s.slug = :store"
        params["store"] = store

    rows = (await session.execute(text(f"""
        SELECT
            ph.recorded_at::text,
            ph.price_tenge,
            s.display_name AS store_name,
            s.slug         AS store_slug
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
            store_slug=r.store_slug,
        )
        for r in rows
    ]
