"""Full reviewer snapshot — composes funnel/heatmap for complete proof."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dashboard.period import resolve_analysis_period
from app.domain.reviewer.proof import build_reviewer_proof_lite
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.store_repository import StoreRepository
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService


async def build_reviewer_snapshot(
    session: AsyncSession,
    store_id: UUID,
    *,
    demo_store_id: str,
    api_key: str,
) -> dict[str, object]:
    """Aggregate reviewer-facing proof for dashboard and API meta."""
    period_start, period_end = await resolve_analysis_period(
        session, store_id, None, None
    )

    store_repo = StoreRepository(session)
    funnel = FunnelService(
        funnel_repository=FunnelRepository(session),
        store_repository=store_repo,
        event_repository=EventRepository(session),
        session=session,
    )
    heatmap = HeatmapService(
        heatmap_repository=HeatmapRepository(session),
        store_repository=store_repo,
    )
    funnel_resp = await funnel.get_funnel(
        store_id, from_ts=period_start, to_ts=period_end
    )
    heatmap_resp = await heatmap.get_heatmap(
        store_id, from_ts=period_start, to_ts=period_end
    )

    lite = await build_reviewer_proof_lite(
        session,
        store_id,
        period_start,
        period_end,
        funnel_stages=funnel_resp.stages,
        heatmap_zones=heatmap_resp.zones,
    )
    base = f"/api/v1/stores/{demo_store_id}"
    now = datetime.now(tz=UTC)

    return {
        "generated_at": now.isoformat(),
        "demo_store_id": demo_store_id,
        "api_key_hint": api_key,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "dashboard_url": "/dashboard/",
        "docs_url": "/docs",
        "checks_passed": lite["checks_passed"],
        "checks_total": lite["checks_total"],
        "ready_for_review": lite["ready_for_review"],
        "checks": lite["checks"],
        "summary": lite["summary"],
        "endpoints": {
            "health": "/health",
            "metrics": f"{base}/metrics?metric=visitor.count",
            "funnel": f"{base}/funnel",
            "heatmap": f"{base}/heatmap",
            "anomalies": f"{base}/anomalies",
            "dashboard_summary": f"{base}/dashboard/summary",
        },
        "api_base_url": "http://localhost:8000",
        "api_guide_url": "/reviewer/api",
        "reviewer_mode": True,
        "reviewer_proof": lite["summary"],
    }
