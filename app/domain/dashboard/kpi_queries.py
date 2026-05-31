"""Real KPI aggregations from ingested pipeline events and transactions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Transaction, VisitSession

STAFF_ZONE_TYPES = ("staff_only", "ignore")


def _json_flag_true(column):
    """Match JSON/JSONB booleans and string flags without `IS TRUE` on jsonb."""
    text = func.lower(func.coalesce(column.as_string(), ""))
    return text.in_(("true", "1"))


def _is_customer_class(class_label):
    return or_(class_label.is_(None), class_label != "staff")


def _is_customer_zone(zone_type):
    return or_(zone_type.is_(None), zone_type.notin_(STAFF_ZONE_TYPES))


def _period_filters(model_occurred_at, from_ts: datetime, to_ts: datetime):
    return (
        model_occurred_at >= from_ts,
        model_occurred_at <= to_ts,
    )


async def count_customer_sessions(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    staff_meta = cast(VisitSession.metadata_["staff"], String)
    stmt = (
        select(func.count())
        .select_from(VisitSession)
        .where(
            VisitSession.store_id == store_id,
            VisitSession.started_at >= from_ts,
            VisitSession.started_at <= to_ts,
            or_(
                VisitSession.metadata_.is_(None),
                staff_meta.is_(None),
                staff_meta.notin_(("true", "True", "1")),
            ),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_session_exits(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    staff_meta = cast(VisitSession.metadata_["staff"], String)
    stmt = (
        select(func.count())
        .select_from(VisitSession)
        .where(
            VisitSession.store_id == store_id,
            VisitSession.ended_at.isnot(None),
            VisitSession.ended_at >= from_ts,
            VisitSession.ended_at <= to_ts,
            or_(
                VisitSession.metadata_.is_(None),
                staff_meta.is_(None),
                staff_meta.notin_(("true", "True", "1")),
            ),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_store_entry_events(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    flag = Event.payload["is_store_entry"]
    explicit = (
        select(func.count())
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type == "vision.zone.entered",
            *_period_filters(Event.occurred_at, from_ts, to_ts),
            _json_flag_true(flag),
        )
    )
    count = int((await session.execute(explicit)).scalar_one())
    if count > 0:
        return count

    zone_type = func.lower(cast(Event.payload["zone_type"], String))
    class_label = func.lower(cast(Event.payload["class_label"], String))
    entry_zones = (
        select(func.count(func.distinct(cast(Event.payload["external_track_id"], String))))
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type == "vision.zone.entered",
            *_period_filters(Event.occurred_at, from_ts, to_ts),
            zone_type.in_(("entry_threshold", "entrance", "entry")),
            _is_customer_class(class_label),
            cast(Event.payload["external_track_id"], String).isnot(None),
        )
    )
    threshold = int((await session.execute(entry_zones)).scalar_one())
    if threshold > 0:
        return threshold

    any_track = (
        select(func.count(func.distinct(cast(Event.payload["external_track_id"], String))))
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type == "vision.zone.entered",
            *_period_filters(Event.occurred_at, from_ts, to_ts),
            _is_customer_class(class_label),
            _is_customer_zone(zone_type),
            cast(Event.payload["external_track_id"], String).isnot(None),
        )
    )
    return int((await session.execute(any_track)).scalar_one())


async def count_store_exit_events(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    flag = Event.payload["is_store_exit"]
    explicit = (
        select(func.count())
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type.in_(("vision.zone.entered", "vision.zone.exited")),
            *_period_filters(Event.occurred_at, from_ts, to_ts),
            _json_flag_true(flag),
        )
    )
    count = int((await session.execute(explicit)).scalar_one())
    if count > 0:
        return count

    class_label = func.lower(cast(Event.payload["class_label"], String))
    track_ended = (
        select(func.count(func.distinct(cast(Event.payload["external_track_id"], String))))
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type == "vision.track.ended",
            *_period_filters(Event.occurred_at, from_ts, to_ts),
            _is_customer_class(class_label),
            cast(Event.payload["external_track_id"], String).isnot(None),
        )
    )
    return int((await session.execute(track_ended)).scalar_one())


async def count_reentry_events(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    flag = cast(Event.payload["is_reentry"], String)
    stmt = (
        select(func.count())
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type == "vision.zone.entered",
            *_period_filters(Event.occurred_at, from_ts, to_ts),
            flag.in_(("true", "True", "1")),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_staff_filtered_events(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    class_label = func.lower(cast(Event.payload["class_label"], String))
    zone_type = func.lower(cast(Event.payload["zone_type"], String))
    stmt = (
        select(func.count())
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type.in_(
                ("vision.zone.entered", "vision.zone.exited", "vision.frame.processed")
            ),
            *_period_filters(Event.occurred_at, from_ts, to_ts),
            or_(
                class_label == "staff",
                zone_type.in_(STAFF_ZONE_TYPES),
            ),
        )
    )
    event_count = int((await session.execute(stmt)).scalar_one())

    staff_meta = cast(VisitSession.metadata_["staff"], String)
    session_stmt = (
        select(func.count())
        .select_from(VisitSession)
        .where(
            VisitSession.store_id == store_id,
            VisitSession.started_at >= from_ts,
            VisitSession.started_at <= to_ts,
            staff_meta.in_(("true", "True", "1")),
        )
    )
    session_count = int((await session.execute(session_stmt)).scalar_one())
    return event_count + session_count


async def sum_completed_revenue(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> Decimal:
    stmt = (
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .select_from(Transaction)
        .where(
            Transaction.store_id == store_id,
            Transaction.status == "completed",
            Transaction.occurred_at >= from_ts,
            Transaction.occurred_at <= to_ts,
        )
    )
    result = await session.execute(stmt)
    value = result.scalar_one()
    return Decimal(str(value)) if value is not None else Decimal("0")


async def count_pipeline_events(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    stmt = (
        select(func.count())
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            *_period_filters(Event.occurred_at, from_ts, to_ts),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_completed_purchases(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    stmt = (
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.store_id == store_id,
            Transaction.status == "completed",
            Transaction.occurred_at >= from_ts,
            Transaction.occurred_at <= to_ts,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_linked_purchases(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> int:
    """Transactions correlated to a CCTV track via journey_link metadata."""
    rows = (
        await session.execute(
            select(Transaction.metadata_).where(
                Transaction.store_id == store_id,
                Transaction.status == "completed",
                Transaction.occurred_at >= from_ts,
                Transaction.occurred_at <= to_ts,
            )
        )
    ).scalars()
    return sum(1 for meta in rows if (meta or {}).get("external_track_id"))


async def aggregate_top_brands(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
    *,
    limit: int = 5,
) -> list[dict]:
    """Top brands by NMV from transaction metadata (real POS CSV)."""
    rows = (
        await session.execute(
            select(Transaction.metadata_, Transaction.amount).where(
                Transaction.store_id == store_id,
                Transaction.status == "completed",
                Transaction.occurred_at >= from_ts,
                Transaction.occurred_at <= to_ts,
            )
        )
    ).all()
    totals: dict[str, Decimal] = {}
    for meta, _amount in rows:
        meta = meta or {}
        for item in meta.get("brands") or []:
            name = str(item.get("brand_name") or "Unknown")
            totals[name] = totals.get(name, Decimal("0")) + Decimal(str(item.get("nmv") or "0"))
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"brand_name": name, "revenue": float(rev)} for name, rev in ranked]


async def aggregate_top_categories(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
    *,
    limit: int = 5,
) -> list[dict]:
    rows = (
        await session.execute(
            select(Transaction.metadata_).where(
                Transaction.store_id == store_id,
                Transaction.status == "completed",
                Transaction.occurred_at >= from_ts,
                Transaction.occurred_at <= to_ts,
            )
        )
    ).scalars()
    totals: dict[str, Decimal] = {}
    for meta in rows:
        meta = meta or {}
        for item in meta.get("categories") or []:
            name = str(item.get("category") or "unknown")
            totals[name] = totals.get(name, Decimal("0")) + Decimal(str(item.get("nmv") or "0"))
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"category": name, "revenue": float(rev)} for name, rev in ranked]


async def get_store_last_event_at(
    session: AsyncSession,
    store_id: UUID,
) -> datetime | None:
    stmt = (
        select(func.max(Event.occurred_at))
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type.in_(
                ("vision.frame.processed", "vision.zone.entered", "vision.zone.exited")
            ),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

