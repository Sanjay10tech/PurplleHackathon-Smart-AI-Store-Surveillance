from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.models import (
    Anomaly,
    Event,
    Store,
    StoreMetric,
    Tenant,
    Transaction,
    VisitSession,
)
from app.schemas.events import IngestOutcome


class StoreRepositoryProtocol(ABC):
    @abstractmethod
    async def get_by_id(self, store_id: UUID) -> Store | None: ...

    @abstractmethod
    async def get_tenant_id_for_store(self, store_id: UUID) -> UUID | None: ...

    @abstractmethod
    async def get_default_tenant(self, slug: str) -> Tenant | None: ...


class EventRepositoryProtocol(ABC):
    @abstractmethod
    async def create_idempotent(self, event: Event) -> tuple[Event, IngestOutcome]: ...

    @abstractmethod
    async def get_by_id(self, event_id: UUID) -> Event | None: ...

    @abstractmethod
    async def get_existing_ids(self, event_ids: list[UUID]) -> set[UUID]: ...

    @abstractmethod
    async def get_by_idempotency_key(self, key: str) -> Event | None: ...

    @abstractmethod
    async def list_by_store(
        self,
        store_id: UUID,
        *,
        event_types: list[str] | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]: ...

    @abstractmethod
    async def count_by_store_and_type(
        self,
        store_id: UUID,
        event_types: list[str],
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> int: ...

    @abstractmethod
    async def count_distinct_visitor_ids(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> int: ...

    @abstractmethod
    async def count_sessions_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> int: ...

    @abstractmethod
    async def visitor_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]: ...

    @abstractmethod
    async def queue_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]: ...

    @abstractmethod
    async def footfall_trend_series(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[tuple[datetime, float, int]]: ...


class VisitSessionRepositoryProtocol(ABC):
    @abstractmethod
    async def create(self, session: VisitSession) -> VisitSession: ...

    @abstractmethod
    async def get_by_id(self, session_id: UUID) -> VisitSession | None: ...

    @abstractmethod
    async def get_active_by_track(
        self, store_id: UUID, external_track_id: str
    ) -> VisitSession | None: ...

    @abstractmethod
    async def list_by_store(
        self,
        store_id: UUID,
        *,
        status: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[VisitSession]: ...

    @abstractmethod
    async def update(self, session: VisitSession) -> VisitSession: ...


class TransactionRepositoryProtocol(ABC):
    @abstractmethod
    async def create_idempotent(self, transaction: Transaction) -> tuple[Transaction, bool]: ...

    @abstractmethod
    async def get_by_id(self, transaction_id: UUID) -> Transaction | None: ...

    @abstractmethod
    async def get_by_external_ref(self, store_id: UUID, external_ref: str) -> Transaction | None: ...

    @abstractmethod
    async def list_by_store(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Transaction]: ...


class AnomalyRepositoryProtocol(ABC):
    @abstractmethod
    async def create(self, anomaly: Anomaly) -> Anomaly: ...

    @abstractmethod
    async def get_by_id(self, anomaly_id: UUID) -> Anomaly | None: ...

    @abstractmethod
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
    ) -> list[Anomaly]: ...

    @abstractmethod
    async def resolve(self, anomaly_id: UUID, resolved_at: datetime) -> Anomaly | None: ...


class StoreMetricRepositoryProtocol(ABC):
    @abstractmethod
    async def upsert(self, metric: StoreMetric) -> StoreMetric: ...

    @abstractmethod
    async def get_by_store(
        self,
        store_id: UUID,
        metric_name: str,
        *,
        granularity: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> list[StoreMetric]: ...

    @abstractmethod
    async def has_data_for_store(self, store_id: UUID) -> bool: ...


# Legacy protocols (deprecated — use EventRepository / StoreMetricRepository)
class DomainEventRepositoryProtocol(ABC):
    @abstractmethod
    async def create(self, event: object) -> object: ...

    @abstractmethod
    async def get_by_idempotency_key(self, key: str) -> object | None: ...

    @abstractmethod
    async def count_by_store_and_type(
        self,
        store_id: UUID,
        event_types: list[str],
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> int: ...


class AnalyticsRepositoryProtocol(ABC):
    @abstractmethod
    async def get_rollups(
        self,
        store_id: UUID,
        metric_name: str,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> list[object]: ...

    @abstractmethod
    async def has_data_for_store(self, store_id: UUID) -> bool: ...


class FunnelRepositoryProtocol(ABC):
    @abstractmethod
    async def list_sessions_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[VisitSession]: ...

    @abstractmethod
    async def list_funnel_events_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[Event]: ...

    @abstractmethod
    async def list_purchases_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[Transaction]: ...

    @abstractmethod
    async def get_sessions_by_ids(
        self,
        store_id: UUID,
        session_ids: list[UUID],
    ) -> list[VisitSession]: ...


class HeatmapRepositoryProtocol(ABC):
    @abstractmethod
    async def list_zone_events_in_period(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[Event]: ...

    @abstractmethod
    async def get_latest_feed_timestamp(
        self,
        store_id: UUID,
        *,
        before: datetime | None = None,
    ) -> datetime | None: ...


class HealthRepositoryProtocol(ABC):
    @abstractmethod
    async def get_last_feed_event_at(
        self,
        store_id: UUID | None = None,
    ) -> datetime | None: ...
