"""Роутер магазинов: список активных магазинов с информацией о доставке."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.deps import get_db

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────

class StoreOut(BaseModel):
    id: UUID
    slug: str
    display_name: str
    logo_url: Optional[str] = None
    website_url: Optional[str] = None
    delivery_cost_tenge: float
    delivery_free_threshold: float
    min_order_tenge: float
    avg_delivery_minutes: int
    scrape_health_score: float
    is_active: bool
    products_count: int


# ── Endpoints ─────────────────────────────────────────────────

@router.get("", response_model=list[StoreOut])
async def list_stores(session: AsyncSession = Depends(get_db)):
    """
    Список всех активных магазинов с информацией о доставке
    и количеством товаров в наличии.
    """
    rows = (await session.execute(text("""
        SELECT
            s.id, s.slug, s.display_name, s.logo_url, s.website_url,
            s.delivery_cost_tenge, s.delivery_free_threshold,
            s.min_order_tenge, s.avg_delivery_minutes,
            s.scrape_health_score, s.is_active,
            COUNT(DISTINCT cp.product_id) AS products_count
        FROM stores s
        LEFT JOIN current_prices cp ON cp.store_id = s.id AND cp.in_stock = true
        WHERE s.is_active = true
        GROUP BY s.id
        ORDER BY s.display_name
    """))).fetchall()

    return [
        StoreOut(
            id=r.id,
            slug=r.slug,
            display_name=r.display_name,
            logo_url=r.logo_url,
            website_url=r.website_url,
            delivery_cost_tenge=float(r.delivery_cost_tenge),
            delivery_free_threshold=float(r.delivery_free_threshold),
            min_order_tenge=float(r.min_order_tenge),
            avg_delivery_minutes=r.avg_delivery_minutes,
            scrape_health_score=float(r.scrape_health_score),
            is_active=r.is_active,
            products_count=r.products_count,
        )
        for r in rows
    ]
