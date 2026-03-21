"""Роутер магазинов."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID
from decimal import Decimal

from shared.models import Store
from services.api.deps import get_db

router = APIRouter()


class StoreOut(BaseModel):
    id: UUID
    slug: str
    display_name: str
    logo_url: Optional[str]
    website_url: Optional[str]
    delivery_cost_tenge: Optional[float]
    delivery_free_threshold: Optional[float]
    min_order_tenge: Optional[float]
    avg_delivery_minutes: Optional[int]
    scrape_health_score: float
    is_active: bool
    products_count: Optional[int]


@router.get("", response_model=list[StoreOut])
async def list_stores(session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(text("""
        SELECT
            s.*,
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
            delivery_cost_tenge=float(r.delivery_cost_tenge) if r.delivery_cost_tenge else None,
            delivery_free_threshold=float(r.delivery_free_threshold) if r.delivery_free_threshold else None,
            min_order_tenge=float(r.min_order_tenge) if r.min_order_tenge else None,
            avg_delivery_minutes=r.avg_delivery_minutes,
            scrape_health_score=float(r.scrape_health_score),
            is_active=r.is_active,
            products_count=r.products_count,
        )
        for r in rows
    ]
