"""WebSocket live analytics feed for dashboard bonus."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.dependencies import get_analytics_service, get_funnel_service, get_heatmap_service
from app.services.analytics_service import AnalyticsService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/stores/{store_id}/live")
async def store_live_feed(
    websocket: WebSocket,
    store_id: UUID,
    funnel_service: Annotated[FunnelService, Depends(get_funnel_service)],
    heatmap_service: Annotated[HeatmapService, Depends(get_heatmap_service)],
    analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> None:
    """Push funnel, heatmap, and metrics snapshots every five seconds."""
    api_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    from app.config import get_settings

    settings = get_settings()
    if settings.api_key_required:
        from app.security import _accepted_keys

        accepted = _accepted_keys(settings)
        if accepted and (not api_key or api_key.strip() not in accepted):
            await websocket.close(code=4401)
            return

    await websocket.accept()
    try:
        while True:
            funnel = await funnel_service.get_funnel(store_id)
            heatmap = await heatmap_service.get_heatmap(store_id)
            metrics = await analytics_service.get_metrics(store_id)
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "store_id": str(store_id),
                    "funnel": funnel.model_dump(mode="json"),
                    "heatmap": heatmap.model_dump(mode="json"),
                    "metrics": metrics.model_dump(mode="json"),
                }
            )
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        return
