from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from app.dependencies import get_analytics_service, get_anomaly_service, get_dashboard_service, get_funnel_service, get_heatmap_service, get_reid_evidence_service
from app.schemas.anomalies import StoreAnomaliesResponse
from app.schemas.common import StoreMetricsResponse
from app.schemas.dashboard import StoreDashboardSummaryResponse
from app.schemas.funnel import StoreFunnelResponse
from app.schemas.journey import StoreRetailJourneysResponse
from app.schemas.reid import ReIdEvidenceResponse
from app.schemas.heatmap import StoreHeatmapResponse
from app.security import require_api_key
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.dashboard_service import DashboardService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService
from app.services.reid_evidence_service import ReIdEvidenceService

router = APIRouter(
    prefix="/stores",
    tags=["stores", "analytics"],
    dependencies=[Depends(require_api_key)],
)

DemoStoreId = Annotated[
    UUID,
    Path(
        description="Demo Brigade Road store (use this UUID for evaluation)",
        examples=["00000000-0000-0000-0000-000000000101"],
    ),
]


@router.get(
    "/{store_id}/metrics",
    response_model=StoreMetricsResponse,
    summary="Store footfall and metric time series",
)
async def get_store_metrics(
    store_id: DemoStoreId,
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    granularity: Annotated[str, Query(pattern="^(minute|hour|day)$")] = "hour",
    metric: Annotated[str, Query()] = "footfall.count",
) -> StoreMetricsResponse:
    return await service.get_metrics(
        store_id,
        from_ts=from_ts,
        to_ts=to_ts,
        granularity=granularity,
        metric=metric,
    )


@router.get(
    "/{store_id}/funnel",
    response_model=StoreFunnelResponse,
    summary="Session-based conversion funnel with drop-off and re-entry metrics",
)
async def get_store_funnel(
    store_id: DemoStoreId,
    service: Annotated[FunnelService, Depends(get_funnel_service)],
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
) -> StoreFunnelResponse:
    return await service.get_funnel(store_id, from_ts=from_ts, to_ts=to_ts)


@router.get(
    "/{store_id}/funnel/journeys",
    response_model=StoreRetailJourneysResponse,
    summary="Linked retail journeys — Visitor → Zone → Billing → Purchase",
)
async def get_store_retail_journeys(
    store_id: DemoStoreId,
    service: Annotated[FunnelService, Depends(get_funnel_service)],
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    complete_only: Annotated[bool, Query(description="Return only 4-stage complete journeys")] = False,
) -> StoreRetailJourneysResponse:
    return await service.get_retail_journeys(
        store_id,
        from_ts=from_ts,
        to_ts=to_ts,
        complete_only=complete_only,
    )


@router.get(
    "/{store_id}/reid/evidence",
    response_model=ReIdEvidenceResponse,
    summary="Cross-camera Re-ID evidence from ingested vision events",
)
async def get_store_reid_evidence(
    store_id: DemoStoreId,
    service: Annotated[ReIdEvidenceService, Depends(get_reid_evidence_service)],
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
) -> ReIdEvidenceResponse:
    return await service.get_evidence(store_id, from_ts=from_ts, to_ts=to_ts)


@router.get(
    "/{store_id}/heatmap",
    response_model=StoreHeatmapResponse,
    summary="Zone visit heatmap with dwell and normalized scores",
)
async def get_store_heatmap(
    store_id: DemoStoreId,
    service: Annotated[HeatmapService, Depends(get_heatmap_service)],
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
) -> StoreHeatmapResponse:
    return await service.get_heatmap(store_id, from_ts=from_ts, to_ts=to_ts)


@router.get(
    "/{store_id}/anomalies",
    response_model=StoreAnomaliesResponse,
    summary="Store anomaly detections with severity and suggested actions",
)
async def get_store_anomalies(
    store_id: DemoStoreId,
    service: Annotated[AnomalyService, Depends(get_anomaly_service)],
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
) -> StoreAnomaliesResponse:
    return await service.get_anomalies(store_id, from_ts=from_ts, to_ts=to_ts)


@router.get(
    "/{store_id}/dashboard/summary",
    response_model=StoreDashboardSummaryResponse,
    summary="Aggregated dashboard KPIs from real pipeline data",
)
async def get_store_dashboard_summary(
    store_id: DemoStoreId,
    service: Annotated[DashboardService, Depends(get_dashboard_service)],
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
) -> StoreDashboardSummaryResponse:
    return await service.get_summary(store_id, from_ts=from_ts, to_ts=to_ts)
