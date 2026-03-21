"""FastAPI — основной бэкенд Astana Prices."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from shared.config import settings
from services.api.routers import products, categories, cart, auth, stores

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 API запущен")
    yield
    logger.info("API завершён")


app = FastAPI(
    title="Astana Prices API",
    version="1.0.0",
    description="Агрегатор цен на продукты в Астане",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# ── Middleware ─────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ── Роутеры ────────────────────────────────────────────────────
app.include_router(auth.router,       prefix="/api/v1/auth",       tags=["auth"])
app.include_router(products.router,   prefix="/api/v1/products",   tags=["products"])
app.include_router(categories.router, prefix="/api/v1/categories", tags=["categories"])
app.include_router(stores.router,     prefix="/api/v1/stores",     tags=["stores"])
app.include_router(cart.router,       prefix="/api/v1/cart",       tags=["cart"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
