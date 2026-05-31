"""Legacy tables retained for backward compatibility during migration."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DomainEvent(Base):
    __tablename__ = "domain_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_domain_events_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_domain_events_aggregate", "aggregate_type", "aggregate_id", "occurred_at"),
        Index("ix_domain_events_event_type", "event_type"),
    )


class AnalyticsRollup(Base):
    __tablename__ = "analytics_rollups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    value: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sample_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    store: Mapped["Store"] = relationship(back_populates="rollups")

    __table_args__ = (
        Index("ix_analytics_rollups_store_metric", "store_id", "metric_name", "bucket_start"),
        UniqueConstraint(
            "store_id",
            "camera_id",
            "metric_name",
            "bucket_start",
            "dimensions",
            name="uq_analytics_rollups_bucket",
        ),
    )


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_type: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_analytics_snapshots_store_type", "store_id", "snapshot_type", "period_start"),
    )
