from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalyticsRollup
from app.repositories.interfaces import AnalyticsRepositoryProtocol


class AnalyticsRepository(AnalyticsRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_rollups(
        self,
        store_id: UUID,
        metric_name: str,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> list[AnalyticsRollup]:
        stmt = (
            select(AnalyticsRollup)
            .where(
                AnalyticsRollup.store_id == store_id,
                AnalyticsRollup.metric_name == metric_name,
            )
            .order_by(AnalyticsRollup.bucket_start.asc())
        )
        if from_ts is not None:
            stmt = stmt.where(AnalyticsRollup.bucket_start >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(AnalyticsRollup.bucket_end <= to_ts)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def has_data_for_store(self, store_id: UUID) -> bool:
        stmt = select(func.count()).select_from(AnalyticsRollup).where(
            AnalyticsRollup.store_id == store_id
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one()) > 0
