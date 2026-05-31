from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Anomaly
from app.repositories.crud.base import CRUDRepository
from app.repositories.interfaces import AnomalyRepositoryProtocol


class AnomalyRepository(CRUDRepository[Anomaly], AnomalyRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Anomaly)

    async def list_by_store(
        self,
        store_id: UUID,
        *,
        severity: str | None = None,
        unresolved_only: bool = False,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Anomaly]:
        stmt = (
            select(Anomaly)
            .where(Anomaly.store_id == store_id)
            .order_by(Anomaly.detected_at.desc())
            .offset(offset)
            .limit(min(limit, 500))
        )
        if severity is not None:
            stmt = stmt.where(Anomaly.severity == severity)
        if unresolved_only:
            stmt = stmt.where(Anomaly.resolved_at.is_(None))
        if from_ts is not None:
            stmt = stmt.where(Anomaly.detected_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(Anomaly.detected_at <= to_ts)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def resolve(self, anomaly_id: UUID, resolved_at: datetime) -> Anomaly | None:
        anomaly = await self.get_by_id(anomaly_id)
        if anomaly is None:
            return None
        anomaly.resolved_at = resolved_at
        return await self.update(anomaly)
