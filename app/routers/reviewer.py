"""Public reviewer snapshot — no API key required."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db_session
from app.domain.reviewer.api_catalog import build_reviewer_api_guide
from app.domain.reviewer.snapshot import build_reviewer_snapshot
from app.schemas.reviewer import ReviewerApiGuideResponse, ReviewerSnapshotResponse

router = APIRouter(tags=["reviewer"])


def _request_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get(
    "/reviewer",
    response_model=ReviewerSnapshotResponse,
    summary="Purple Tech 2-minute proof checklist (public)",
)
async def get_reviewer_snapshot(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReviewerSnapshotResponse:
    """
    Single endpoint for evaluators: proves 5-video ingest, events, entries/exits,
    re-entry, conversion, funnel, and heatmap from live PostgreSQL data.
    """
    store_id = UUID(settings.pos_store_id)
    payload = await build_reviewer_snapshot(
        session,
        store_id,
        demo_store_id=settings.pos_store_id,
        api_key=settings.effective_api_key,
    )
    payload["reviewer_mode"] = settings.reviewer_mode
    payload["api_key_hint"] = settings.effective_api_key
    return ReviewerSnapshotResponse.model_validate(payload)


@router.get(
    "/reviewer/api",
    response_model=ReviewerApiGuideResponse,
    summary="Reviewer API guide — demo URLs and curl examples (public)",
)
async def get_reviewer_api_guide(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReviewerApiGuideResponse:
    """
    How to call every demo endpoint with `X-API-Key: purple-demo-key`.
    Use this when Swagger or the dashboard is unavailable.
    """
    guide = build_reviewer_api_guide(settings, api_base_url=_request_base_url(request))
    return ReviewerApiGuideResponse.model_validate(guide)
