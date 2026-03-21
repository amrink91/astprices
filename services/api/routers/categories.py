"""Роутер категорий: список с количеством товаров."""
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

class CategoryOut(BaseModel):
    id: UUID
    slug: str
    name: str
    icon_emoji: Optional[str] = None
    parent_id: Optional[UUID] = None
    sort_order: int
    product_count: int


# ── Endpoints ─────────────────────────────────────────────────

@router.get("", response_model=list[CategoryOut])
async def list_categories(session: AsyncSession = Depends(get_db)):
    """
    Список всех категорий с количеством товаров, у которых есть
    хотя бы одна цена в current_prices (in_stock).
    """
    rows = (await session.execute(text("""
        SELECT
            c.id, c.slug, c.name_ru, c.icon_emoji,
            c.parent_id, c.sort_order,
            COUNT(DISTINCT cp.product_id) AS product_count
        FROM categories c
        LEFT JOIN products p       ON p.category_id = c.id
        LEFT JOIN current_prices cp ON cp.product_id = p.id AND cp.in_stock = true
        GROUP BY c.id
        ORDER BY c.sort_order, c.name_ru
    """))).fetchall()

    return [
        CategoryOut(
            id=r.id,
            slug=r.slug,
            name=r.name_ru,
            icon_emoji=r.icon_emoji,
            parent_id=r.parent_id,
            sort_order=r.sort_order,
            product_count=r.product_count,
        )
        for r in rows
    ]
