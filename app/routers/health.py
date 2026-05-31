from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.config import Settings, get_settings
from app.dependencies import get_health_service
from app.schemas.health import HealthResponse, ReadinessCheck, ReviewerHealthSummary
from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """
    Production health — process liveness, database connectivity, feed freshness,
    STALE_FEED detection, and lightweight reviewer quick-start links.

    Full proof checklist lives on GET /reviewer (not here — avoids slow funnel/heatmap queries).
    """
    body, http_status = await service.get_health()
    response.status_code = http_status

    api_key = settings.effective_api_key
    base = f"/api/v1/stores/{settings.pos_store_id}"
    reviewer = ReviewerHealthSummary(
        demo_store_id=settings.pos_store_id,
        api_key_hint=api_key,
        reviewer_mode=settings.reviewer_mode,
        api_guide_url="/reviewer/api",
        endpoints={
            "metrics": f"{base}/metrics?metric=visitor.count",
            "funnel": f"{base}/funnel",
            "heatmap": f"{base}/heatmap",
            "anomalies": f"{base}/anomalies",
            "dashboard_summary": f"{base}/dashboard/summary",
        },
        feed_note=(
            "Feed marked stale — batch CCTV + POS data in PostgreSQL is still valid for review."
            if body.stale_feed
            else None
        ),
    )

    return body.model_copy(update={"reviewer": reviewer})

@router.get("/health/ready", response_model=ReadinessCheck)
async def readiness(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> ReadinessCheck:
    """Readiness probe — database must accept connections."""
    status_label, checks, ready = await service.get_readiness()

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessCheck(status=status_label, checks=checks)
