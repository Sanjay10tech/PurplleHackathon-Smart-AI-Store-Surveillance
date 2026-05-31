"""Project hourly footfall metrics from ingested vision events into store_metrics."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import create_engine, create_session_factory
from app.domain.vision.filters import is_customer_metric_event
from app.models import Event, StoreMetric
from app.repositories.store_metric_repository import StoreMetricRepository

DEMO_STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")


def _hour_bucket(dt: datetime) -> datetime:
    start = dt.replace(minute=0, second=0, microsecond=0)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return start


async def project_footfall(*, hours_back: int = 24) -> int:
    engine = create_engine()
    session_factory = create_session_factory(engine)
    now = datetime.now(tz=UTC)
    window_start = now - timedelta(hours=hours_back)

    async with session_factory() as session:
        repo = StoreMetricRepository(session)
        stmt = select(Event.occurred_at, Event.payload).where(
            Event.store_id == DEMO_STORE_ID,
            Event.event_type == "vision.zone.entered",
            Event.occurred_at >= window_start,
            Event.occurred_at <= now,
        )
        rows = (await session.execute(stmt)).all()

        buckets: dict[datetime, int] = {}
        for occurred_at, payload in rows:
            if not is_customer_metric_event(payload or {}):
                continue
            bucket_start = _hour_bucket(occurred_at)
            buckets[bucket_start] = buckets.get(bucket_start, 0) + 1

        written = 0
        for bucket_start, value in sorted(buckets.items()):
            metric = StoreMetric(
                id=uuid.uuid4(),
                store_id=DEMO_STORE_ID,
                metric_name="footfall.count",
                bucket_start=bucket_start,
                bucket_end=bucket_start + timedelta(hours=1),
                granularity="hour",
                dimensions={},
                value=float(value),
                sample_count=value,
            )
            await repo.upsert(metric)
            written += 1
        await session.commit()
        return written


async def main() -> None:
    count = await project_footfall()
    print(f"Projected {count} footfall metric bucket(s) for store {DEMO_STORE_ID}")


if __name__ == "__main__":
    asyncio.run(main())
