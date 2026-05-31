"""Hourly trend series from ingested vision events (PostgreSQL + portable fallback)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.heatmap.constants import DEFAULT_QUEUE_ZONE_TYPES
from app.domain.vision.filters import is_customer_metric_event
from app.models import Event, Transaction
from app.services.metrics_projector_service import _hour_bucket

QUEUE_ZONE_TYPES_SQL = ", ".join(f"'{z}'" for z in sorted(DEFAULT_QUEUE_ZONE_TYPES))


def _pg_params(store_id: UUID, from_ts: datetime, to_ts: datetime) -> dict:
    return {"store_id": store_id, "from_ts": from_ts, "to_ts": to_ts}


async def _portable_zone_events(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[tuple[datetime, dict]]:
    stmt = select(Event.occurred_at, Event.payload).where(
        Event.store_id == store_id,
        Event.occurred_at >= from_ts,
        Event.occurred_at <= to_ts,
        Event.event_type == "vision.zone.entered",
    )
    rows = (await session.execute(stmt)).all()
    return [
        (occurred_at, payload or {})
        for occurred_at, payload in rows
        if isinstance(payload, dict)
    ]


async def footfall_trend_series(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[tuple[datetime, float, int]]:
    """Customer zone-enter events per hour bucket."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        rows = (
            await session.execute(
                text(
                    """
                    SELECT date_trunc('hour', occurred_at) AS bucket_start,
                           COUNT(*) AS value
                    FROM events
                    WHERE store_id = :store_id
                      AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                      AND event_type = 'vision.zone.entered'
                      AND lower(coalesce(payload->>'class_label', '')) != 'staff'
                      AND lower(coalesce(payload->>'zone_type', ''))
                          NOT IN ('staff_only', 'ignore')
                    GROUP BY 1
                    ORDER BY 1
                    """
                ),
                _pg_params(store_id, from_ts, to_ts),
            )
        ).all()
        return [
            (row[0], float(row[1]), int(row[1]))
            for row in rows
            if row[0] is not None
        ]

    buckets: dict[datetime, int] = defaultdict(int)
    for occurred_at, payload in await _portable_zone_events(
        session, store_id, from_ts, to_ts
    ):
        if is_customer_metric_event(payload):
            buckets[_hour_bucket(occurred_at)] += 1

    return [
        (bucket, float(count), count)
        for bucket, count in sorted(buckets.items())
    ]


async def visitor_trend_series(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[tuple[datetime, float, int]]:
    """Distinct customer track IDs per hour bucket."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        rows = (
            await session.execute(
                text(
                    """
                    SELECT date_trunc('hour', occurred_at) AS bucket_start,
                           COUNT(DISTINCT track_id) AS value
                    FROM (
                        SELECT occurred_at, payload->>'external_track_id' AS track_id
                        FROM events
                        WHERE store_id = :store_id
                          AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                          AND payload->>'external_track_id' IS NOT NULL
                          AND payload->>'external_track_id' != ''
                          AND lower(payload->>'external_track_id') != 'null'
                          AND lower(coalesce(payload->>'class_label', '')) != 'staff'
                          AND lower(coalesce(payload->>'zone_type', ''))
                              NOT IN ('staff_only', 'ignore')
                    ) AS tracks
                    WHERE track_id IS NOT NULL
                    GROUP BY 1
                    ORDER BY 1
                    """
                ),
                _pg_params(store_id, from_ts, to_ts),
            )
        ).all()
        return [
            (row[0], float(row[1]), int(row[1]))
            for row in rows
            if row[0] is not None
        ]

    buckets: dict[datetime, set[str]] = defaultdict(set)
    stmt = select(Event.occurred_at, Event.payload).where(
        Event.store_id == store_id,
        Event.occurred_at >= from_ts,
        Event.occurred_at <= to_ts,
    )
    for occurred_at, payload in (await session.execute(stmt)).all():
        if not isinstance(payload, dict) or not is_customer_metric_event(payload):
            continue
        track_id = payload.get("external_track_id")
        if not track_id or str(track_id).lower() == "null":
            continue
        buckets[_hour_bucket(occurred_at)].add(str(track_id))

    return [
        (bucket, float(len(tracks)), len(tracks))
        for bucket, tracks in sorted(buckets.items())
    ]


async def queue_trend_series(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[tuple[datetime, float, int]]:
    """Billing-queue zone enters per hour bucket."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT date_trunc('hour', occurred_at) AS bucket_start,
                           COUNT(*) AS value
                    FROM events
                    WHERE store_id = :store_id
                      AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                      AND event_type = 'vision.zone.entered'
                      AND lower(coalesce(payload->>'class_label', '')) != 'staff'
                      AND (
                        lower(coalesce(payload->>'zone_type', '')) IN ({QUEUE_ZONE_TYPES_SQL})
                        OR lower(coalesce(payload->>'zone_id', '')) LIKE '%queue%'
                        OR lower(coalesce(payload->>'zone_id', '')) LIKE '%billing%'
                        OR lower(coalesce(payload->>'zone_id', '')) LIKE '%checkout%'
                      )
                    GROUP BY 1
                    ORDER BY 1
                    """
                ),
                _pg_params(store_id, from_ts, to_ts),
            )
        ).all()
        return [
            (row[0], float(row[1]), int(row[1]))
            for row in rows
            if row[0] is not None
        ]

    buckets: dict[datetime, int] = defaultdict(int)
    for occurred_at, payload in await _portable_zone_events(
        session, store_id, from_ts, to_ts
    ):
        if not is_customer_metric_event(payload):
            continue
        zone_type = str(payload.get("zone_type", "")).lower()
        zone_id = str(payload.get("zone_id", "")).lower()
        is_queue = (
            zone_type in DEFAULT_QUEUE_ZONE_TYPES
            or "queue" in zone_id
            or "billing" in zone_id
            or "checkout" in zone_id
        )
        if is_queue:
            buckets[_hour_bucket(occurred_at)] += 1

    return [
        (bucket, float(count), count)
        for bucket, count in sorted(buckets.items())
    ]


async def pos_revenue_trend_series(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[tuple[datetime, float, int]]:
    """Hourly POS revenue (NMV) from transactions table."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        rows = (
            await session.execute(
                text(
                    """
                    SELECT date_trunc('hour', occurred_at) AS bucket_start,
                           COALESCE(SUM(amount), 0) AS value,
                           COUNT(*) AS sample_count
                    FROM transactions
                    WHERE store_id = :store_id
                      AND status = 'completed'
                      AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                    GROUP BY 1
                    ORDER BY 1
                    """
                ),
                _pg_params(store_id, from_ts, to_ts),
            )
        ).all()
        return [
            (row[0], float(row[1]), int(row[2]))
            for row in rows
            if row[0] is not None
        ]

    buckets: dict[datetime, float] = defaultdict(float)
    counts: dict[datetime, int] = defaultdict(int)
    stmt = select(Transaction.occurred_at, Transaction.amount).where(
        Transaction.store_id == store_id,
        Transaction.status == "completed",
        Transaction.occurred_at >= from_ts,
        Transaction.occurred_at <= to_ts,
    )
    for occurred_at, amount in (await session.execute(stmt)).all():
        bucket = _hour_bucket(occurred_at)
        buckets[bucket] += float(amount)
        counts[bucket] += 1

    return [
        (bucket, buckets[bucket], counts[bucket])
        for bucket in sorted(buckets.keys())
    ]


async def pos_purchase_trend_series(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[tuple[datetime, float, int]]:
    """Hourly POS order count from transactions table."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        rows = (
            await session.execute(
                text(
                    """
                    SELECT date_trunc('hour', occurred_at) AS bucket_start,
                           COUNT(*) AS value
                    FROM transactions
                    WHERE store_id = :store_id
                      AND status = 'completed'
                      AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                    GROUP BY 1
                    ORDER BY 1
                    """
                ),
                _pg_params(store_id, from_ts, to_ts),
            )
        ).all()
        return [
            (row[0], float(row[1]), int(row[1]))
            for row in rows
            if row[0] is not None
        ]

    buckets: dict[datetime, int] = defaultdict(int)
    stmt = select(Transaction.occurred_at).where(
        Transaction.store_id == store_id,
        Transaction.status == "completed",
        Transaction.occurred_at >= from_ts,
        Transaction.occurred_at <= to_ts,
    )
    for (occurred_at,) in (await session.execute(stmt)).all():
        buckets[_hour_bucket(occurred_at)] += 1

    return [
        (bucket, float(count), count)
        for bucket, count in sorted(buckets.items())
    ]
