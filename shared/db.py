"""Подключение к PostgreSQL — async SQLAlchemy"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
