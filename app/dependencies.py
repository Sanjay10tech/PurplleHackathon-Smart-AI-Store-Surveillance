import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db_session
from app.logging_config import bind_context
from app.repositories.anomaly_repository import AnomalyRepository
from app.repositories.event_repository import EventRepository
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.health_repository import HealthRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.store_repository import StoreRepository
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.event_ingestion_service import EventIngestionService
from app.services.event_validation_service import EventValidationService
from app.services.dashboard_service import DashboardService
from app.services.funnel_service import FunnelService
from app.services.health_service import HealthService
from app.services.heatmap_service import HeatmapService
from app.services.metrics_projector_service import MetricsProjectorService
from app.services.reid_evidence_service import ReIdEvidenceService


async def get_correlation_id(
    request: Request,
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-ID")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> str:
    trace_id = (
        x_trace_id
        or x_correlation_id
        or getattr(request.state, "trace_id", None)
        or str(uuid.uuid4())
    )
    bind_context(trace_id=trace_id, correlation_id=trace_id)
    return trace_id


def get_app_settings() -> Settings:
    return get_settings()


async def get_store_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StoreRepository:
    return StoreRepository(session)


async def get_event_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EventRepository:
    return EventRepository(session)


async def get_event_validation_service(
    store_repo: Annotated[StoreRepository, Depends(get_store_repository)],
) -> EventValidationService:
    return EventValidationService(store_repository=store_repo)


async def get_store_metric_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StoreMetricRepository:
    return StoreMetricRepository(session)


async def get_anomaly_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnomalyRepository:
    return AnomalyRepository(session)


async def get_event_ingestion_service(
    event_repo: Annotated[EventRepository, Depends(get_event_repository)],
    validation_service: Annotated[EventValidationService, Depends(get_event_validation_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> EventIngestionService:
    return EventIngestionService(
        event_repository=event_repo,
        validation_service=validation_service,
        settings=settings,
        metrics_projector=MetricsProjectorService(event_repo._session),
    )


async def get_health_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> HealthService:
    return HealthService(
        health_repository=HealthRepository(session),
        settings=settings,
    )


async def get_funnel_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    store_repo: Annotated[StoreRepository, Depends(get_store_repository)],
) -> FunnelService:
    return FunnelService(
        funnel_repository=FunnelRepository(session),
        store_repository=store_repo,
        event_repository=EventRepository(session),
        session=session,
    )


async def get_heatmap_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    store_repo: Annotated[StoreRepository, Depends(get_store_repository)],
) -> HeatmapService:
    return HeatmapService(
        heatmap_repository=HeatmapRepository(session),
        store_repository=store_repo,
        session=session,
    )


async def get_anomaly_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    store_repo: Annotated[StoreRepository, Depends(get_store_repository)],
    anomaly_repo: Annotated[AnomalyRepository, Depends(get_anomaly_repository)],
) -> AnomalyService:
    return AnomalyService(
        heatmap_repository=HeatmapRepository(session),
        funnel_repository=FunnelRepository(session),
        store_repository=store_repo,
        anomaly_repository=anomaly_repo,
        event_repository=EventRepository(session),
        session=session,
    )


async def get_analytics_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    metric_repo: Annotated[StoreMetricRepository, Depends(get_store_metric_repository)],
    store_repo: Annotated[StoreRepository, Depends(get_store_repository)],
    event_repo: Annotated[EventRepository, Depends(get_event_repository)],
    anomaly_repo: Annotated[AnomalyRepository, Depends(get_anomaly_repository)],
) -> AnalyticsService:
    return AnalyticsService(
        metric_repository=metric_repo,
        store_repository=store_repo,
        event_repository=event_repo,
        anomaly_repository=anomaly_repo,
        session=session,
    )


async def get_reid_evidence_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    store_repo: Annotated[StoreRepository, Depends(get_store_repository)],
) -> ReIdEvidenceService:
    return ReIdEvidenceService(
        event_repository=EventRepository(session),
        store_repository=store_repo,
    )


async def get_dashboard_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    store_repo: Annotated[StoreRepository, Depends(get_store_repository)],
    funnel_service: Annotated[FunnelService, Depends(get_funnel_service)],
    heatmap_service: Annotated[HeatmapService, Depends(get_heatmap_service)],
    analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    anomaly_service: Annotated[AnomalyService, Depends(get_anomaly_service)],
) -> DashboardService:
    return DashboardService(
        session=session,
        store_repository=store_repo,
        funnel_service=funnel_service,
        heatmap_service=heatmap_service,
        analytics_service=analytics_service,
        anomaly_service=anomaly_service,
    )


async def log_request_context(
    request: Request,
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> AsyncGenerator[None, None]:
    bind_context(
        trace_id=correlation_id,
        correlation_id=correlation_id,
        method=request.method,
        path=request.url.path,
    )
    yield
