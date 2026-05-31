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
    from app.models.legacy import AnalyticsRollup
    from app.models.store_metric import StoreMetric
    from app.models.tenant import Tenant
    from app.models.transaction import Transaction
    from app.models.visit_session import VisitSession


class Store(Base, TimestampMixin):
    __tablename__ = "stores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    geo_location: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="stores")
    events: Mapped[list["Event"]] = relationship(back_populates="store")
    sessions: Mapped[list["VisitSession"]] = relationship(back_populates="store")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="store")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="store")
    metrics: Mapped[list["StoreMetric"]] = relationship(back_populates="store")
    rollups: Mapped[list["AnalyticsRollup"]] = relationship(back_populates="store")

    __table_args__ = (Index("ix_stores_tenant_id", "tenant_id"),)
