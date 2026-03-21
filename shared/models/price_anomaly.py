from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, UUIDMixin


class PriceAnomaly(Base, UUIDMixin):
    __tablename__ = "price_anomalies"

    store_product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_product: Mapped["StoreProduct"] = relationship("StoreProduct", back_populates="anomalies")

    detected_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    anomaly_type:  Mapped[str]      = mapped_column(String(50), nullable=False, index=True)  # spike|drop|outlier
    old_price:     Mapped[Optional[Decimal]] = mapped_column(Numeric(10,2), nullable=True)
    new_price:     Mapped[Decimal]           = mapped_column(Numeric(10,2), nullable=False)
    deviation_pct: Mapped[float]             = mapped_column(nullable=False)

    gemini_explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published:    Mapped[bool]              = mapped_column(Boolean, default=False, index=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved:     Mapped[bool]              = mapped_column(Boolean, default=False)
