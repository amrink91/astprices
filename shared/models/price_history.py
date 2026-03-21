from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class PriceHistory(Base):
    """История цен — партиционированная по месяцам"""
    __tablename__ = "price_history"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    store_product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_product: Mapped["StoreProduct"] = relationship("StoreProduct", back_populates="price_history")

    price_tenge:     Mapped[Decimal]           = mapped_column(Numeric(10,2), nullable=False)
    old_price_tenge: Mapped[Optional[Decimal]] = mapped_column(Numeric(10,2), nullable=True)
    in_stock:        Mapped[bool]              = mapped_column(Boolean, default=True)
    is_promoted:     Mapped[bool]              = mapped_column(Boolean, default=False)

    scrape_run_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
