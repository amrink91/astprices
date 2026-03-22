"""
Нормализация товаров через Gemini — категории и канонические названия.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.models import Category, Product, StoreProduct, Store, PriceHistory
from shared.scrapers.base import RawProduct
from shared.utils.gemini_client import get_gemini_client

logger = logging.getLogger("normalizer")


class ProductNormalizer:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.gemini = get_gemini_client()
        self._cat_cache: dict[str, UUID] = {}   # slug → UUID
        self._store_cache: dict[str, UUID] = {} # slug → UUID

    async def _load_caches(self) -> None:
        cats = (await self.session.execute(select(Category))).scalars().all()
        self._cat_cache = {c.slug: c.id for c in cats}
        stores = (await self.session.execute(select(Store))).scalars().all()
        self._store_cache = {s.slug: s.id for s in stores}

    # ─────────────────────────────────────────────────────────────
    # Публичный API
    # ─────────────────────────────────────────────────────────────

    async def normalize_batch(self, raw_products: list[RawProduct]) -> int:
        await self._load_caches()
        processed = 0
        batch_size = settings.gemini_normalize_batch_size

        for i in range(0, len(raw_products), batch_size):
            batch = raw_products[i: i + batch_size]
            try:
                normalized = await self._call_gemini(batch)
                processed += await self._save(batch, normalized)
            except Exception as e:
                logger.error(f"Батч {i // batch_size}: {e}")
                processed += await self._save_raw_fallback(batch)

        return processed

    # ─────────────────────────────────────────────────────────────
    # Gemini вызов
    # ─────────────────────────────────────────────────────────────

    async def _call_gemini(self, batch: list[RawProduct]) -> list[dict]:
        products_input = [
            {
                "id": str(i),
                "store": p.store_slug,
                "name": p.name_raw,
                "price": str(p.price_tenge),
                "unit": p.unit or "",
                "category_hint": " > ".join(p.category_path) if p.category_path else "",
            }
            for i, p in enumerate(batch)
        ]
        results = await self.gemini.normalize_products(products_input)
        by_id = {str(r.get("id", "")): r for r in results}
        return [by_id.get(str(i), {}) for i in range(len(batch))]

    # ─────────────────────────────────────────────────────────────
    # Сохранение нормализованных данных
    # ─────────────────────────────────────────────────────────────

    async def _save(self, raw_batch: list[RawProduct], norm_batch: list[dict]) -> int:
        saved = 0
        for raw, norm in zip(raw_batch, norm_batch):
            if not norm:
                continue
            try:
                confidence = float(norm.get("confidence", 0.0))
                canonical_name = norm.get("canonical_name") or raw.name_raw
                cat_id = self._cat_cache.get(norm.get("category_slug", "other"))

                product_id = await self._get_or_create_product(
                    canonical_name=canonical_name,
                    category_id=cat_id,
                    subcategory=norm.get("subcategory"),
                    brand=norm.get("brand"),
                    unit=norm.get("unit"),
                    unit_size=norm.get("unit_size"),
                    confidence=confidence,
                )
                await self._upsert_store_product(raw, product_id)

                if confidence >= 0.8:
                    await self._embed_if_missing(product_id, canonical_name, norm)

                saved += 1
            except Exception as e:
                logger.error(f"Save '{raw.name_raw}': {e}")

        await self.session.commit()
        return saved

    async def _get_or_create_product(
        self, canonical_name: str, category_id: Optional[UUID],
        subcategory: Optional[str], brand: Optional[str],
        unit: Optional[str], unit_size: Optional[float], confidence: float,
    ) -> UUID:
        existing = (await self.session.execute(
            select(Product).where(Product.canonical_name == canonical_name)
        )).scalar_one_or_none()

        if existing:
            return existing.id

        p = Product(
            canonical_name=canonical_name,
            category_id=category_id,
            subcategory=subcategory,
            brand=brand,
            unit=unit,
            unit_size=Decimal(str(unit_size)) if unit_size else None,
            normalization_confidence=confidence,
        )
        self.session.add(p)
        await self.session.flush()
        return p.id

    async def _upsert_store_product(self, raw: RawProduct, product_id: UUID) -> None:
        store_id = self._store_cache.get(raw.store_slug)
        if not store_id:
            logger.error(f"Магазин '{raw.store_slug}' не найден в кэше!")
            return

        stmt = (
            insert(StoreProduct)
            .values(
                product_id=product_id,
                store_id=store_id,
                store_sku=raw.store_sku,
                store_url=raw.store_url,
                store_image_url=raw.store_image_url,
                name_raw=raw.name_raw,
                price_tenge=raw.price_tenge,
                old_price_tenge=raw.old_price_tenge,
                in_stock=raw.in_stock,
                is_promoted=raw.is_promoted,
                promo_label=raw.promo_label,
            )
            .on_conflict_do_update(
                constraint="uq_store_sku",
                set_={
                    "price_tenge": raw.price_tenge,
                    "old_price_tenge": raw.old_price_tenge,
                    "in_stock": raw.in_stock,
                    "is_promoted": raw.is_promoted,
                    "promo_label": raw.promo_label,
                    "store_image_url": raw.store_image_url,
                    "product_id": product_id,
                    "updated_at": datetime.utcnow(),
                },
            )
            .returning(StoreProduct.id)
        )
        result = await self.session.execute(stmt)
        sp_id = result.scalar_one()

        # Всегда пишем в историю
        self.session.add(PriceHistory(
            store_product_id=sp_id,
            price_tenge=raw.price_tenge,
            old_price_tenge=raw.old_price_tenge,
            in_stock=raw.in_stock,
            is_promoted=raw.is_promoted,
        ))

    async def _embed_if_missing(self, product_id: UUID, canonical_name: str, norm: dict) -> None:
        has_emb = (await self.session.execute(
            select(Product.name_embedding).where(Product.id == product_id)
        )).scalar_one_or_none()
        if has_emb:
            return
        try:
            import json as _json
            text = " ".join(filter(None, [
                canonical_name, norm.get("category_slug", ""),
                norm.get("brand", ""), norm.get("subcategory", ""),
            ]))
            emb = await self.gemini.get_embedding(text)
            emb_str = _json.dumps(emb)
            await self.session.execute(
                update(Product).where(Product.id == product_id).values(name_embedding=emb_str)
            )
        except Exception as e:
            logger.warning(f"Embedding failed '{canonical_name}': {e}")

    async def _save_raw_fallback(self, batch: list[RawProduct]) -> int:
        """Сохраняем без нормализации — попадут в повторную обработку"""
        saved = 0
        for raw in batch:
            store_id = self._store_cache.get(raw.store_slug)
            if not store_id:
                continue
            try:
                stmt = (
                    insert(StoreProduct)
                    .values(
                        store_id=store_id, store_sku=raw.store_sku,
                        store_url=raw.store_url, store_image_url=raw.store_image_url,
                        name_raw=raw.name_raw, price_tenge=raw.price_tenge,
                        old_price_tenge=raw.old_price_tenge, in_stock=raw.in_stock,
                        is_promoted=raw.is_promoted, promo_label=raw.promo_label,
                    )
                    .on_conflict_do_update(
                        constraint="uq_store_sku",
                        set_={
                            "price_tenge": raw.price_tenge,
                            "old_price_tenge": raw.old_price_tenge,
                            "in_stock": raw.in_stock,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                )
                await self.session.execute(stmt)
                saved += 1
            except Exception as e:
                logger.error(f"Fallback save '{raw.name_raw}': {e}")
        await self.session.commit()
        return saved
