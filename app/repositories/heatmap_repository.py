from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.heatmap.constants import FEED_EVENT_TYPES, ZONE_ENTER_EVENT_TYPE, ZONE_EXIT_EVENT_TYPE
from app.models import Event
from app.repositories.interfaces import HeatmapRepositoryProtocol


class HeatmapRepository(HeatmapRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_zone_events_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[Event]:
        stmt = (
            select(Event)
            .where(
                Event.store_id == store_id,
                Event.occurred_at >= from_ts,
                Event.occurred_at <= to_ts,
                Event.event_type.in_([ZONE_ENTER_EVENT_TYPE, ZONE_EXIT_EVENT_TYPE]),
            )
            .order_by(Event.occurred_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_feed_timestamp(
        self,
        store_id: UUID,
        *,
        before: datetime | None = None,
    ) -> datetime | None:
        stmt = (
            select(func.max(Event.occurred_at))
            .where(
                Event.store_id == store_id,
                Event.event_type.in_(FEED_EVENT_TYPES),
            )
        )
        if before is not None:
            stmt = stmt.where(Event.occurred_at <= before)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
