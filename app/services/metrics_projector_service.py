"""Automatic footfall projection from ingested zone-enter events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.vision.filters import is_customer_metric_event
from app.logging_config import get_logger
from app.models import Event, StoreMetric
from app.repositories.store_metric_repository import StoreMetricRepository

logger = get_logger(__name__)


def _hour_bucket(dt: datetime) -> datetime:
    start = dt.replace(minute=0, second=0, microsecond=0)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return start


class MetricsProjectorService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._metrics = StoreMetricRepository(session)

    async def project_footfall(
        self,
        store_id: uuid.UUID,
        *,
        hours_back: int = 24,
    ) -> int:
        """Upsert hourly footfall.count buckets for customer zone-enter events."""
        now = datetime.now(tz=UTC)
        window_start = now - timedelta(hours=hours_back)

        stmt = select(Event.occurred_at, Event.payload).where(
            Event.store_id == store_id,
            Event.event_type == "vision.zone.entered",
            Event.occurred_at >= window_start,
            Event.occurred_at <= now,
        )
        rows = (await self._session.execute(stmt)).all()

        buckets: dict[datetime, int] = {}
        for occurred_at, payload in rows:
            if not is_customer_metric_event(payload or {}):
                continue
            bucket_start = _hour_bucket(occurred_at)
            buckets[bucket_start] = buckets.get(bucket_start, 0) + 1

        written = 0
        for bucket_start, value in sorted(buckets.items()):
            await self._metrics.upsert(
                StoreMetric(
                    id=uuid.uuid4(),
                    store_id=store_id,
                    metric_name="footfall.count",
                    bucket_start=bucket_start,
                    bucket_end=bucket_start + timedelta(hours=1),
                    granularity="hour",
                    dimensions={},
                    value=float(value),
                    sample_count=value,
                )
            )
            written += 1

        if written:
            logger.info(
                "metrics_projected",
                store_id=str(store_id),
                buckets=written,
                hours_back=hours_back,
            )
        return written
