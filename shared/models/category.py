from typing import Optional
from uuid import UUID
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin


class Category(Base, UUIDMixin, TimestampMixin):
    """Дерево категорий — Gemini строит автоматически"""
    __tablename__ = "categories"

    name:       Mapped[str]           = mapped_column(String(128), nullable=False)
    slug:       Mapped[str]           = mapped_column(String(200), nullable=False, unique=True, index=True)
    icon_emoji: Mapped[Optional[str]] = mapped_column(String(10),  nullable=True)
    sort_order: Mapped[int]           = mapped_column(Integer,     default=0)

    parent_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent:   Mapped[Optional["Category"]] = relationship("Category", back_populates="children", remote_side="Category.id")
    children: Mapped[list["Category"]]     = relationship("Category", back_populates="parent")
    products: Mapped[list["Product"]]      = relationship("Product",  back_populates="category")

    def __repr__(self) -> str:
        return f"<Category {self.name}>"
