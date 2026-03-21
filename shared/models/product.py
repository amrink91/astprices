from decimal import Decimal
from typing import Optional
from uuid import UUID
from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin


class Product(Base, UUIDMixin, TimestampMixin):
    """Канонический (нормализованный) товар — один на весь рынок"""
    __tablename__ = "products"

    canonical_name:  Mapped[str]             = mapped_column(Text,        nullable=False, index=True)
    name_embedding:  Mapped[Optional[list]]  = mapped_column(Vector(768), nullable=True)   # pgvector

    category_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category:    Mapped[Optional["Category"]] = relationship("Category", back_populates="products")
    subcategory: Mapped[Optional[str]]        = mapped_column(String(200), nullable=True)

    brand:     Mapped[Optional[str]]     = mapped_column(String(200), nullable=True, index=True)
    unit:      Mapped[Optional[str]]     = mapped_column(String(20),  nullable=True)
    unit_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(10,3), nullable=True)
    barcode:   Mapped[Optional[str]]     = mapped_column(String(100), nullable=True, index=True)
    image_url: Mapped[Optional[str]]     = mapped_column(Text,        nullable=True)
    normalization_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)

    store_products: Mapped[list["StoreProduct"]] = relationship("StoreProduct", back_populates="product")

    __table_args__ = (
        Index("idx_products_embedding_hnsw", name_embedding,
              postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"name_embedding": "vector_cosine_ops"}),
    )

    def __repr__(self) -> str:
        return f"<Product {self.canonical_name}>"
