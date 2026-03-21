from decimal import Decimal
from typing import Optional
from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin


class Store(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "stores"

    slug:         Mapped[str]     = mapped_column(String(50),  unique=True, nullable=False, index=True)
    display_name: Mapped[str]     = mapped_column(String(100), nullable=False)
    base_url:     Mapped[str]     = mapped_column(Text,        nullable=False)
    logo_url:     Mapped[Optional[str]] = mapped_column(Text,  nullable=True)

    delivery_cost_tenge:       Mapped[Decimal] = mapped_column(Numeric(10,2), nullable=False)
    delivery_free_threshold:   Mapped[Decimal] = mapped_column(Numeric(10,2), nullable=False)
    min_order_tenge:           Mapped[Decimal] = mapped_column(Numeric(10,2), default=Decimal("0"))
    avg_delivery_minutes:      Mapped[int]     = mapped_column(Integer,       default=60)

    is_active:           Mapped[bool]  = mapped_column(Boolean, default=True)
    scrape_health_score: Mapped[float] = mapped_column(default=1.0)
    scraper_config:      Mapped[dict]  = mapped_column(JSONB,   default=dict)

    store_products: Mapped[list["StoreProduct"]] = relationship("StoreProduct", back_populates="store")
    scrape_runs:    Mapped[list["ScrapeRun"]]    = relationship("ScrapeRun",    back_populates="store")

    def __repr__(self) -> str:
        return f"<Store {self.slug}>"
