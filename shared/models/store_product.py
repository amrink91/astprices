from decimal import Decimal
from typing import Optional
from uuid import UUID
from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin


class StoreProduct(Base, UUIDMixin, TimestampMixin):
    """Вариант товара в конкретном магазине с актуальной ценой"""
    __tablename__ = "store_products"

    product_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product: Mapped[Optional["Product"]] = relationship("Product", back_populates="store_products")

    store_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store: Mapped["Store"] = relationship("Store", back_populates="store_products")

    store_sku:       Mapped[str]           = mapped_column(String(200), nullable=False)
    store_url:       Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    store_image_url: Mapped[Optional[str]] = mapped_column(Text,        nullable=True)
    name_raw:        Mapped[str]           = mapped_column(Text,        nullable=False)

    price_tenge:     Mapped[Decimal]           = mapped_column(Numeric(10,2), nullable=False)
    old_price_tenge: Mapped[Optional[Decimal]] = mapped_column(Numeric(10,2), nullable=True)
    price_per_unit:  Mapped[Optional[Decimal]] = mapped_column(Numeric(10,2), nullable=True)

    in_stock:    Mapped[bool]          = mapped_column(Boolean, default=True,  index=True)
    is_promoted: Mapped[bool]          = mapped_column(Boolean, default=False, index=True)
    promo_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    price_history: Mapped[list["PriceHistory"]] = relationship("PriceHistory", back_populates="store_product")
    anomalies:     Mapped[list["PriceAnomaly"]] = relationship("PriceAnomaly", back_populates="store_product")

    __table_args__ = (UniqueConstraint("store_id", "store_sku", name="uq_store_sku"),)

    @property
    def discount_pct(self) -> Optional[float]:
        if self.old_price_tenge and self.old_price_tenge > 0:
            return round(float(self.old_price_tenge - self.price_tenge) / float(self.old_price_tenge) * 100, 1)
        return None
