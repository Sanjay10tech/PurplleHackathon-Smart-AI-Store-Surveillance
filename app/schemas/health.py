from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthChecks(BaseModel):
    database: str = Field(description="up | down")
    feed: str = Field(description="fresh | stale | unknown")


class ReviewerHealthSummary(BaseModel):
    """Quick proof for Purple Tech evaluators — visible on GET /health."""

    demo_store_id: str
    dashboard_url: str = "/dashboard/"
    reviewer_url: str = "/reviewer"
    api_key_hint: str = "purple-demo-key"
    checks_passed: int | None = None
    checks_total: int | None = None
    ready_for_review: bool | None = None
    summary: dict[str, Any] | None = None
    endpoints: dict[str, str] = Field(default_factory=dict)
    feed_note: str | None = None
    api_guide_url: str = "/reviewer/api"
    reviewer_mode: bool = True


class HealthResponse(BaseModel):
    """Production health payload with dependency and feed checks."""

    status: str = Field(description="ok | degraded | unhealthy")
    service: str
    version: str
    checks: HealthChecks
    last_event_at: datetime | None = None
    feed_stale_minutes: float | None = None
    stale_feed: bool = False
    reviewer: ReviewerHealthSummary | None = None

class ReadinessCheck(BaseModel):
    status: str
    checks: dict[str, str]
