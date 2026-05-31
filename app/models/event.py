import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.anomaly import Anomaly
    from app.models.store import Store
    from app.models.visit_session import VisitSession


class Event(Base):
    """
    Append-only event log for ingestion, vision, and analytics pipelines.

    Deduplication: partial unique index on idempotency_key (see migration).
    """

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    store: Mapped["Store"] = relationship(back_populates="events")
    session: Mapped["VisitSession | None"] = relationship(back_populates="events")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="event")

    __table_args__ = (
        Index("ix_events_store_occurred", "store_id", "occurred_at"),
        Index("ix_events_store_type_occurred", "store_id", "event_type", "occurred_at"),
        Index("ix_events_tenant_occurred", "tenant_id", "occurred_at"),
        Index("ix_events_correlation_id", "correlation_id"),
        Index("ix_events_session_id", "session_id"),
    )
