from datetime import datetime
from uuid import UUID

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DomainEvent
from app.repositories.interfaces import DomainEventRepositoryProtocol


class DomainEventRepository(DomainEventRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, event: DomainEvent) -> DomainEvent:
        self._session.add(event)
        await self._session.flush()
        await self._session.refresh(event)
        return event

    async def get_by_idempotency_key(self, key: str) -> DomainEvent | None:
        stmt = select(DomainEvent).where(DomainEvent.idempotency_key == key)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_by_store_and_type(
        self,
        store_id: UUID,
        event_types: list[str],
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> int:
        store_id_str = str(store_id)
        stmt = select(func.count()).select_from(DomainEvent).where(
            DomainEvent.event_type.in_(event_types),
            cast(DomainEvent.payload["store_id"], String) == store_id_str,
        )
        if from_ts is not None:
            stmt = stmt.where(DomainEvent.occurred_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(DomainEvent.occurred_at <= to_ts)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())
