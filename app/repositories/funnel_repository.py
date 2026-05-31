from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.funnel.stages import PURCHASE_EVENT_TYPE, ZONE_ENTER_EVENT_TYPE
from app.models import Event, Transaction, VisitSession
from app.repositories.interfaces import FunnelRepositoryProtocol


class FunnelRepository(FunnelRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_sessions_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[VisitSession]:
        stmt = (
            select(VisitSession)
            .where(
                VisitSession.store_id == store_id,
                VisitSession.started_at >= from_ts,
                VisitSession.started_at <= to_ts,
            )
            .order_by(VisitSession.started_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_funnel_events_in_period(
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
                or_(
                    Event.event_type == ZONE_ENTER_EVENT_TYPE,
                    Event.event_type == PURCHASE_EVENT_TYPE,
                ),
            )
            .order_by(Event.occurred_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_purchases_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[Transaction]:
        stmt = (
            select(Transaction)
            .where(
                Transaction.store_id == store_id,
                Transaction.occurred_at >= from_ts,
                Transaction.occurred_at <= to_ts,
                Transaction.status == "completed",
            )
            .order_by(Transaction.occurred_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_sessions_by_ids(
        self,
        store_id: UUID,
        session_ids: list[UUID],
    ) -> list[VisitSession]:
        if not session_ids:
            return []
        stmt = select(VisitSession).where(
            VisitSession.store_id == store_id,
            VisitSession.id.in_(session_ids),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
