import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.anomaly import Anomaly
    from app.models.event import Event
    from app.models.store import Store
    from app.models.transaction import Transaction


class VisitSession(Base, TimestampMixin):
    """Customer visit session derived from CCTV tracking (ByteTrack track lifecycle)."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    external_track_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, server_default="{}")

    store: Mapped["Store"] = relationship(back_populates="sessions")
    events: Mapped[list["Event"]] = relationship(back_populates="session")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="session")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="session")

    __table_args__ = (
        Index("ix_sessions_store_started", "store_id", "started_at"),
        Index("ix_sessions_store_status", "store_id", "status"),
        Index("ix_sessions_store_external_track", "store_id", "external_track_id"),
    )
