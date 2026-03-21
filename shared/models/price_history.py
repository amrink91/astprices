from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class PriceHistory(Base):
    """История цен"""
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    store_product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=False
    )
    store_product: Mapped["StoreProduct"] = relationship("StoreProduct", back_populates="price_history")

    price_tenge:     Mapped[Decimal]           = mapped_column(Numeric(12,2), nullable=False)
    old_price_tenge: Mapped[Optional[Decimal]] = mapped_column(Numeric(12,2), nullable=True)
    in_stock:        Mapped[bool]              = mapped_column(Boolean, default=True)
    is_promoted:     Mapped[bool]              = mapped_column(Boolean, default=False)

    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
