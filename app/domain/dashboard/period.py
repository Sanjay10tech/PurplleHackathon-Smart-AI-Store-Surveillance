"""Shared dashboard analysis window — include all ingested data by default."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Transaction


async def resolve_analysis_period(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime | None,
    to_ts: datetime | None,
    *,
    default_hours: int = 24,
) -> tuple[datetime, datetime]:
    """
    Default window spans first ingested event → now (not a rolling 24h clip).

    Explicit ``from_ts`` / ``to_ts`` query params still override.
    """
    end = to_ts or datetime.now(tz=UTC)
    if from_ts is not None:
        return from_ts, end

    stmt = select(func.min(Event.occurred_at)).where(Event.store_id == store_id)
    first_event = (await session.execute(stmt)).scalar_one_or_none()

    tx_stmt = select(func.min(Transaction.occurred_at)).where(
        Transaction.store_id == store_id
    )
    first_tx = (await session.execute(tx_stmt)).scalar_one_or_none()

    first_candidates = [
        ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
        for ts in (first_event, first_tx)
        if ts is not None
    ]
    if first_candidates:
        start = min(first_candidates)
        return start, end

    return end - timedelta(hours=default_hours), end
