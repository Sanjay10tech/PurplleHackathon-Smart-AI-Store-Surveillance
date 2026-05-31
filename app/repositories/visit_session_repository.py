from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import VisitSession
from app.repositories.crud.base import CRUDRepository
from app.repositories.interfaces import VisitSessionRepositoryProtocol


class VisitSessionRepository(CRUDRepository[VisitSession], VisitSessionRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, VisitSession)

    async def get_active_by_track(
        self, store_id: UUID, external_track_id: str
    ) -> VisitSession | None:
        stmt = (
            select(VisitSession)
            .where(
                VisitSession.store_id == store_id,
                VisitSession.external_track_id == external_track_id,
                VisitSession.status == "active",
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_store(
        self,
        store_id: UUID,
        *,
        status: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[VisitSession]:
        stmt = (
            select(VisitSession)
            .where(VisitSession.store_id == store_id)
            .order_by(VisitSession.started_at.desc())
            .offset(offset)
            .limit(min(limit, 500))
        )
        if status is not None:
            stmt = stmt.where(VisitSession.status == status)
        if from_ts is not None:
            stmt = stmt.where(VisitSession.started_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(VisitSession.started_at <= to_ts)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
