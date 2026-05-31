"""Visitor identity counting from ingested vision events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, VisitSession

STAFF_ZONE_TYPES = ("staff_only", "ignore")


def _is_customer_track(payload: dict, track_id: str | None) -> bool:
    if not track_id or str(track_id).lower() == "null":
        return False
    if str(payload.get("class_label", "")).lower() == "staff":
        return False
    if str(payload.get("zone_type", "")).lower() in STAFF_ZONE_TYPES:
        return False
    return True


async def _count_distinct_tracks_postgres(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    """Distinct customer external_track_id from journey zone events (not frame detections)."""
    stmt = text(
        """
        SELECT COUNT(DISTINCT track_id) FROM (
            SELECT payload->>'external_track_id' AS track_id
            FROM events
            WHERE store_id = :store_id
              AND occurred_at >= :from_ts AND occurred_at <= :to_ts
              AND event_type IN ('vision.zone.entered', 'vision.zone.exited')
              AND payload->>'external_track_id' IS NOT NULL
              AND payload->>'external_track_id' != ''
              AND lower(payload->>'external_track_id') != 'null'
              AND lower(coalesce(payload->>'class_label', '')) != 'staff'
              AND lower(coalesce(payload->>'zone_type', '')) NOT IN ('staff_only', 'ignore')
        ) AS tracks
        WHERE track_id IS NOT NULL AND track_id != ''
        """
    )
    result = await session.execute(
        stmt,
        {"store_id": store_id, "from_ts": from_ts, "to_ts": to_ts},
    )
    return int(result.scalar_one())


async def _count_distinct_tracks_portable(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    track_id = cast(Event.payload["external_track_id"], String)
    class_label = func.lower(cast(Event.payload["class_label"], String))
    zone_type = func.lower(cast(Event.payload["zone_type"], String))

    stmt = (
        select(track_id)
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.occurred_at >= from_ts,
            Event.occurred_at <= to_ts,
            Event.event_type.in_(("vision.zone.entered", "vision.zone.exited")),
            Event.payload["external_track_id"].isnot(None),
            track_id.isnot(None),
            track_id != "",
            func.lower(track_id) != "null",
            or_(Event.payload["class_label"].is_(None), class_label != "staff"),
            or_(
                Event.payload["zone_type"].is_(None),
                ~zone_type.in_(STAFF_ZONE_TYPES),
            ),
        )
        .distinct()
    )
    track_ids = {row[0] for row in (await session.execute(stmt)).all() if row[0]}
    return len(track_ids)


async def count_distinct_visitor_ids(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return await _count_distinct_tracks_postgres(session, store_id, from_ts, to_ts)
    return await _count_distinct_tracks_portable(session, store_id, from_ts, to_ts)


async def count_sessions_in_period(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    staff_flag = cast(VisitSession.metadata_["staff"], String)
    stmt = (
        select(func.count())
        .select_from(VisitSession)
        .where(
            VisitSession.store_id == store_id,
            VisitSession.started_at >= from_ts,
            VisitSession.started_at <= to_ts,
            or_(VisitSession.metadata_.is_(None), staff_flag.is_(None), staff_flag.notin_(("true", "True", "1"))),
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())
