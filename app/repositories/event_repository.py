from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.repositories.crud.base import CRUDRepository
from app.repositories.interfaces import EventRepositoryProtocol
from app.schemas.events import IngestOutcome


class EventRepository(CRUDRepository[Event], EventRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Event)

    async def create_idempotent(self, event: Event) -> tuple[Event, IngestOutcome]:
        existing = await self.get_by_id(event.id)
        if existing is not None:
            return existing, IngestOutcome.DUPLICATE_ID

        if event.idempotency_key:
            by_key = await self.get_by_idempotency_key(event.idempotency_key)
            if by_key is not None:
                return by_key, IngestOutcome.DUPLICATE_KEY

        try:
            async with self._session.begin_nested():
                saved = await self.create(event)
            return saved, IngestOutcome.CREATED
        except IntegrityError:
            existing = await self.get_by_id(event.id)
            if existing is not None:
                return existing, IngestOutcome.DUPLICATE_ID
            if event.idempotency_key:
                by_key = await self.get_by_idempotency_key(event.idempotency_key)
                if by_key is not None:
                    return by_key, IngestOutcome.DUPLICATE_KEY
            raise

    async def get_existing_ids(self, event_ids: list[UUID]) -> set[UUID]:
        if not event_ids:
            return set()
        stmt = select(Event.id).where(Event.id.in_(event_ids))
        result = await self._session.execute(stmt)
        return set(result.scalars().all())

    async def get_by_idempotency_key(self, key: str) -> Event | None:
        stmt = select(Event).where(Event.idempotency_key == key)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_store(
        self,
        store_id: UUID,
        *,
        event_types: list[str] | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        stmt = (
            select(Event)
            .where(Event.store_id == store_id)
            .order_by(Event.occurred_at.desc())
            .offset(offset)
            .limit(min(limit, 500))
        )
        if event_types:
            stmt = stmt.where(Event.event_type.in_(event_types))
        if from_ts is not None:
            stmt = stmt.where(Event.occurred_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(Event.occurred_at <= to_ts)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_store_and_type(
        self,
        store_id: UUID,
        event_types: list[str],
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> int:
        stmt = select(func.count()).select_from(Event).where(
            Event.store_id == store_id,
            Event.event_type.in_(event_types),
        )
        if from_ts is not None:
            stmt = stmt.where(Event.occurred_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(Event.occurred_at <= to_ts)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_distinct_visitor_ids(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> int:
        from app.domain.vision.visitor_count import count_distinct_visitor_ids

        return await count_distinct_visitor_ids(
            self._session, store_id, from_ts, to_ts
        )

    async def count_sessions_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> int:
        from app.domain.vision.visitor_count import count_sessions_in_period

        return await count_sessions_in_period(
            self._session, store_id, from_ts, to_ts
        )

    async def visitor_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]:
        from app.domain.dashboard.trend_queries import visitor_trend_series

        return await visitor_trend_series(
            self._session, store_id, from_ts, to_ts
        )

    async def queue_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]:
        from app.domain.dashboard.trend_queries import queue_trend_series

        return await queue_trend_series(
            self._session, store_id, from_ts, to_ts
        )

    async def footfall_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]:
        from app.domain.dashboard.trend_queries import footfall_trend_series

        return await footfall_trend_series(
            self._session, store_id, from_ts, to_ts
        )

    async def pos_revenue_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]:
        from app.domain.dashboard.trend_queries import pos_revenue_trend_series

        return await pos_revenue_trend_series(
            self._session, store_id, from_ts, to_ts
        )

    async def pos_purchase_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]:
        from app.domain.dashboard.trend_queries import pos_purchase_trend_series

        return await pos_purchase_trend_series(
            self._session, store_id, from_ts, to_ts
        )
