"""Роутер категорий."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from shared.models import Category
from services.api.deps import get_db

router = APIRouter()


class CategoryOut(BaseModel):
    id: UUID
    slug: str
    name: str
    icon_emoji: Optional[str]
    parent_id: Optional[UUID]
    sort_order: int


@router.get("", response_model=list[CategoryOut])
async def list_categories(session: AsyncSession = Depends(get_db)):
    cats = (await session.execute(
        select(Category).order_by(Category.sort_order)
    )).scalars().all()

    return [
        CategoryOut(
            id=c.id, slug=c.slug, name=c.name_ru,
            icon_emoji=c.icon_emoji, parent_id=c.parent_id,
            sort_order=c.sort_order,
        )
        for c in cats
    ]
