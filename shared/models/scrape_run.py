from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, UUIDMixin


class ScrapeRun(Base, UUIDMixin):
    __tablename__ = "scrape_runs"

    store_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    store:    Mapped["Store"] = relationship("Store", back_populates="scrape_runs")

    started_at:  Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status:      Mapped[str]                = mapped_column(String(20), default="running", index=True)

    products_scraped: Mapped[int] = mapped_column(Integer, default=0)
    products_new:     Mapped[int] = mapped_column(Integer, default=0)
    products_updated: Mapped[int] = mapped_column(Integer, default=0)
    products_failed:  Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    error_log:     Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
