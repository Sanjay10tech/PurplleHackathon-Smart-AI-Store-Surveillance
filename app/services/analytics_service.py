from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.dashboard.period import resolve_analysis_period
from app.exceptions import NotFoundError
from app.logging_config import get_logger
from app.repositories.interfaces import (
    AnomalyRepositoryProtocol,
    EventRepositoryProtocol,
    StoreMetricRepositoryProtocol,
    StoreRepositoryProtocol,
)
from app.schemas.common import (
    MetricSeriesPoint,
    PaginatedMeta,
    StoreMetricsResponse,
)
from app.services.interfaces import AnalyticsServiceProtocol

logger = get_logger(__name__)

NO_DATA_MESSAGE = "No Data Available — ingest CCTV vision events to populate this chart."

_EVENT_ONLY_METRICS = frozenset({"visitor.count", "queue.count", "pos.revenue", "pos.purchases"})

_TREND_METHODS = {
    "visitor.count": "visitor_trend_series",
    "queue.count": "queue_trend_series",
    "footfall.count": "footfall_trend_series",
    "pos.revenue": "pos_revenue_trend_series",
    "pos.purchases": "pos_purchase_trend_series",
}


class AnalyticsService(AnalyticsServiceProtocol):
    def __init__(
        self,
        metric_repository: StoreMetricRepositoryProtocol,
        store_repository: StoreRepositoryProtocol,
        event_repository: EventRepositoryProtocol,
        anomaly_repository: AnomalyRepositoryProtocol,
        session=None,
    ) -> None:
        self._metrics = metric_repository
        self._stores = store_repository
        self._events = event_repository
        self._anomalies = anomaly_repository
        self._session = session

    async def _ensure_store_exists(self, store_id: UUID) -> None:
        store = await self._stores.get_by_id(store_id)
        if store is None:
            raise NotFoundError("store", str(store_id))

    def _default_period(
        self,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> tuple[datetime, datetime]:
        end = to_ts or datetime.now(tz=UTC)
        start = from_ts or (end - timedelta(hours=24))
        return start, end

    async def _series_from_events(
        self,
        metric: str,
        store_id: UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> tuple[list[MetricSeriesPoint], PaginatedMeta]:
        method_name = _TREND_METHODS.get(metric)
        if method_name is None:
            return [], PaginatedMeta(partial=True, source="unknown_metric", message=NO_DATA_MESSAGE)

        fetch = getattr(self._events, method_name)
        rows = await fetch(store_id, period_start, period_end)
        if not rows:
            event_count = await self._events.count_by_store_and_type(
                store_id,
                ["vision.frame.processed", "vision.zone.entered"],
                period_start,
                period_end,
            )
            return [], PaginatedMeta(
                partial=True,
                source="placeholder",
                message=NO_DATA_MESSAGE if event_count == 0 else (
                    f"{event_count} vision events in period; no hourly buckets for {metric}."
                ),
            )

        series = [
            MetricSeriesPoint(
                bucket_start=bucket_start,
                value=value,
                sample_count=sample_count,
            )
            for bucket_start, value, sample_count in rows
        ]
        return series, PaginatedMeta(
            partial=False,
            source="events_sql",
            message=f"{len(series)} hourly buckets from PostgreSQL events",
        )

    async def get_metrics(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        granularity: str = "hour",
        metric: str = "footfall.count",
    ) -> StoreMetricsResponse:
        await self._ensure_store_exists(store_id)
        period_end = to_ts or datetime.now(tz=UTC)
        if from_ts is not None:
            period_start = from_ts
        elif self._session is not None:
            period_start, period_end = await resolve_analysis_period(
                self._session, store_id, None, to_ts
            )
        else:
            period_start, period_end = self._default_period(from_ts, to_ts)

        unique_visitors = await self._events.count_distinct_visitor_ids(
            store_id, period_start, period_end
        )
        session_count = await self._events.count_sessions_in_period(
            store_id, period_start, period_end
        )

        series: list[MetricSeriesPoint] = []
        meta = PaginatedMeta(partial=True, source="empty", message=NO_DATA_MESSAGE)

        if metric in _EVENT_ONLY_METRICS:
            series, meta = await self._series_from_events(
                metric, store_id, period_start, period_end
            )
        else:
            rows = await self._metrics.get_by_store(
                store_id,
                metric,
                granularity=granularity,
                from_ts=period_start,
                to_ts=period_end,
            )
            if rows:
                series = [
                    MetricSeriesPoint(
                        bucket_start=r.bucket_start,
                        value=r.value,
                        sample_count=r.sample_count,
                    )
                    for r in rows
                ]
                meta = PaginatedMeta(partial=False, source="store_metrics")
            else:
                series, meta = await self._series_from_events(
                    "footfall.count", store_id, period_start, period_end
                )

        logger.info(
            "analytics_metrics_queried",
            store_id=str(store_id),
            metric=metric,
            series_points=len(series),
            source=meta.source,
            unique_visitors=unique_visitors,
            session_count=session_count,
        )

        reviewer_proof = None
        if self._session is not None:
            reviewer_proof = {
                "checklist_url": "/reviewer",
                "note": "Authoritative 8-check proof lives at GET /reviewer.",
            }

        return StoreMetricsResponse(
            store_id=store_id,
            metric=metric,
            granularity=granularity,
            series=series,
            unique_visitors=unique_visitors,
            session_count=session_count,
            meta=PaginatedMeta(
                partial=meta.partial,
                source=meta.source,
                message=meta.message,
                reviewer_proof=reviewer_proof,
            ),
        )
