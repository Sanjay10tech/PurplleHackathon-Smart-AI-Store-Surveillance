from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StoreMetric
from app.repositories.crud.base import CRUDRepository
from app.repositories.interfaces import StoreMetricRepositoryProtocol


class StoreMetricRepository(CRUDRepository[StoreMetric], StoreMetricRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, StoreMetric)

    async def upsert(self, metric: StoreMetric) -> StoreMetric:
        """Idempotent metric bucket write via unique constraint on bucket dimensions."""
        dialect_name = self._session.get_bind().dialect.name

        if dialect_name == "postgresql":
            stmt = (
                pg_insert(StoreMetric)
                .values(
                    id=metric.id,
                    store_id=metric.store_id,
                    metric_name=metric.metric_name,
                    bucket_start=metric.bucket_start,
                    bucket_end=metric.bucket_end,
                    granularity=metric.granularity,
                    dimensions=metric.dimensions,
                    value=metric.value,
                    sample_count=metric.sample_count,
                )
                .on_conflict_do_update(
                    constraint="uq_store_metrics_bucket",
                    set_={
                        "value": metric.value,
                        "sample_count": metric.sample_count,
                        "bucket_end": metric.bucket_end,
                    },
                )
                .returning(StoreMetric)
            )
            result = await self._session.execute(stmt)
            row = result.scalar_one()
            await self._session.refresh(row)
            return row

        existing = await self._find_bucket(metric)
        if existing is not None:
            existing.value = metric.value
            existing.sample_count = metric.sample_count
            existing.bucket_end = metric.bucket_end
            return await self.update(existing)

        try:
            async with self._session.begin_nested():
                return await self.create(metric)
        except IntegrityError:
            existing = await self._find_bucket(metric)
            if existing is not None:
                existing.value = metric.value
                existing.sample_count = metric.sample_count
                existing.bucket_end = metric.bucket_end
                return await self.update(existing)
            raise

    async def _find_bucket(self, metric: StoreMetric) -> StoreMetric | None:
        stmt = select(StoreMetric).where(
            StoreMetric.store_id == metric.store_id,
            StoreMetric.metric_name == metric.metric_name,
            StoreMetric.bucket_start == metric.bucket_start,
            StoreMetric.granularity == metric.granularity,
            StoreMetric.dimensions == metric.dimensions,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_store(
        self,
        store_id: UUID,
        metric_name: str,
        *,
        granularity: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> list[StoreMetric]:
        stmt = (
            select(StoreMetric)
            .where(
                StoreMetric.store_id == store_id,
                StoreMetric.metric_name == metric_name,
            )
            .order_by(StoreMetric.bucket_start.asc())
        )
        if granularity is not None:
            stmt = stmt.where(StoreMetric.granularity == granularity)
        if from_ts is not None:
            stmt = stmt.where(StoreMetric.bucket_start >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(StoreMetric.bucket_end <= to_ts)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def has_data_for_store(self, store_id: UUID) -> bool:
        stmt = select(func.count()).select_from(StoreMetric).where(StoreMetric.store_id == store_id)
        result = await self._session.execute(stmt)
        return int(result.scalar_one()) > 0
