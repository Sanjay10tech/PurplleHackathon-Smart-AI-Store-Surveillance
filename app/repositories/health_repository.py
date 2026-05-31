from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.heatmap.constants import FEED_EVENT_TYPES
from app.models import Event
from app.repositories.interfaces import HealthRepositoryProtocol


class HealthRepository(HealthRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_last_feed_event_at(
        self,
        store_id: UUID | None = None,
    ) -> datetime | None:
        stmt = select(func.max(Event.occurred_at)).where(
            Event.event_type.in_(FEED_EVENT_TYPES),
        )
        if store_id is not None:
            stmt = stmt.where(Event.store_id == store_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
