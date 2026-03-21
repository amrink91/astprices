"""Checkout microservice — generates cart deep-links and checklists."""
import logging
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.config import settings
from shared.db import get_session
from services.checkout.cart_url_builder import CartURLBuilder

logging.basicConfig(level=settings.log_level, format="%(asctime)s  %(name)-25s %(levelname)-8s  %(message)s")

app = FastAPI(title="Astana Prices — Checkout", docs_url="/docs", redoc_url=None)
builder = CartURLBuilder()


class CheckoutItem(BaseModel):
    product_id: UUID
    store_slug: str
    quantity: int = Field(default=1, ge=1, le=100)


class CheckoutRequest(BaseModel):
    items: list[CheckoutItem] = Field(..., min_length=1, max_length=100)


class CartLinkOut(BaseModel):
    store_slug: str
    store_name: str
    url: str
    fallback_urls: list[str]
    method: str


class CheckoutResponse(BaseModel):
    cart_links: list[CartLinkOut]
    checklist_text: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/checkout", response_model=CheckoutResponse)
async def checkout(req: CheckoutRequest):
    # Group items by store
    store_items: dict[str, list[dict]] = {}
    product_ids = list({i.product_id for i in req.items})

    async with get_session() as session:
        from sqlalchemy import text
        rows = (await session.execute(
            text("""
                SELECT cp.product_id, cp.store_slug, cp.store_sku, cp.store_url,
                       p.canonical_name
                FROM current_prices cp
                JOIN products p ON p.id = cp.product_id
                WHERE cp.product_id = ANY(:ids) AND cp.in_stock = true
            """),
            {"ids": product_ids},
        )).fetchall()

    # Build lookup: (product_id, store_slug) → row
    lookup = {}
    for r in rows:
        lookup[(r.product_id, r.store_slug)] = r

    for item in req.items:
        key = (item.product_id, item.store_slug)
        r = lookup.get(key)
        if not r:
            continue
        store_items.setdefault(item.store_slug, []).append({
            "store_sku": r.store_sku or str(item.product_id),
            "store_url": r.store_url or "",
            "name": r.canonical_name,
            "quantity": item.quantity,
        })

    if not store_items:
        raise HTTPException(400, "Товары не найдены в указанных магазинах")

    cart_links = []
    for store_slug, items in store_items.items():
        link = builder.build(store_slug, items)
        cart_links.append(CartLinkOut(
            store_slug=link.store_slug,
            store_name=link.store_name,
            url=link.url,
            fallback_urls=link.fallback_urls,
            method=link.method,
        ))

    # Generate checklist text (simple version without StoreAssignment objects)
    lines = ["🛒 Список покупок — Астана\n"]
    for store_slug, items in store_items.items():
        link = builder.build(store_slug, items)
        lines.append(f"\n🏪 {link.store_name}:")
        for i in items:
            lines.append(f"  □ {i['name']} × {i['quantity']}")
    checklist_text = "\n".join(lines)

    return CheckoutResponse(cart_links=cart_links, checklist_text=checklist_text)
