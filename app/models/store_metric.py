import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.store import Store


class StoreMetric(Base, TimestampMixin):
    """Pre-aggregated store KPI buckets (footfall, dwell, occupancy)."""

    __tablename__ = "store_metrics"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    granularity: Mapped[str] = mapped_column(String(16), nullable=False, default="hour")
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    value: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sample_count: Mapped[int] = mapped_column(nullable=False, default=0)

    store: Mapped["Store"] = relationship(back_populates="metrics")

    __table_args__ = (
        Index("ix_store_metrics_store_metric_bucket", "store_id", "metric_name", "bucket_start"),
        UniqueConstraint(
            "store_id",
            "metric_name",
            "bucket_start",
            "granularity",
            "dimensions",
            name="uq_store_metrics_bucket",
        ),
    )
