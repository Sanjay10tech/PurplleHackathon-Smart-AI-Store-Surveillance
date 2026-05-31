import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.store import Store
    from app.models.visit_session import VisitSession


class Anomaly(Base):
    """Detected retail anomaly (occupancy, dwell, theft-risk, pipeline errors)."""

    __tablename__ = "anomalies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    anomaly_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    store: Mapped["Store"] = relationship(back_populates="anomalies")
    session: Mapped["VisitSession | None"] = relationship(back_populates="anomalies")
    event: Mapped["Event | None"] = relationship(back_populates="anomalies")

    __table_args__ = (
        Index("ix_anomalies_store_detected", "store_id", "detected_at"),
        Index("ix_anomalies_store_severity_detected", "store_id", "severity", "detected_at"),
        Index("ix_anomalies_store_type_detected", "store_id", "anomaly_type", "detected_at"),
    )
