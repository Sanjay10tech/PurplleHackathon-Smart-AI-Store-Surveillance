from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.schemas.common import (
    MetricSeriesPoint,
    PaginatedMeta,
    StoreMetricsResponse,
)
from app.schemas.events import (
    EventBatchIngestRequest,
    EventBatchIngestResponse,
    EventIngestRequest,
    EventIngestResponse,
)
from app.services.event_validation_service import EventValidationServiceProtocol


class EventIngestionServiceProtocol(ABC):
    @abstractmethod
    async def ingest(self, request: EventIngestRequest, correlation_id: str) -> EventIngestResponse:
        """Accept and persist a single domain event."""
        ...

    @abstractmethod
    async def ingest_batch(
        self,
        batch: EventBatchIngestRequest,
        correlation_id: str,
    ) -> EventBatchIngestResponse:
        """Accept and persist up to 500 events with partial success."""
        ...


class AnalyticsServiceProtocol(ABC):
    @abstractmethod
    async def get_metrics(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        granularity: str = "hour",
        metric: str = "footfall.count",
    ) -> StoreMetricsResponse: ...
