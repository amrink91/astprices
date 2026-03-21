from decimal import Decimal
from typing import Optional
from uuid import UUID
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin


class Product(Base, UUIDMixin, TimestampMixin):
    """Канонический (нормализованный) товар — один на весь рынок"""
    __tablename__ = "products"

    canonical_name:  Mapped[str]            = mapped_column(String(256), nullable=False, unique=True)
    name_embedding:  Mapped[Optional[str]]  = mapped_column(Text, nullable=True)

    category_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    category:    Mapped[Optional["Category"]] = relationship("Category", back_populates="products")
    subcategory: Mapped[Optional[str]]        = mapped_column(String(128), nullable=True)

    brand:     Mapped[Optional[str]]     = mapped_column(String(128), nullable=True)
    unit:      Mapped[Optional[str]]     = mapped_column(String(32),  nullable=True)
    unit_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(10,3), nullable=True)
    normalization_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)

    store_products: Mapped[list["StoreProduct"]] = relationship("StoreProduct", back_populates="product")

    def __repr__(self) -> str:
        return f"<Product {self.canonical_name}>"
