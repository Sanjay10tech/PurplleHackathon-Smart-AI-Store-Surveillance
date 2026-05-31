from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import PaginatedMeta
from app.schemas.funnel import FunnelStageResult
from app.schemas.pos import PosInsights


class DashboardKpiCard(BaseModel):
    key: str
    label: str
    value: float | int | str | None
    formatted: str
    unit: str | None = None
    available: bool = True
    source: str
    category: str = "general"
    business_value: str = ""


class DashboardMetricSpec(BaseModel):
    """Reviewer-facing metric definition with lineage."""

    key: str
    name: str
    data_source: str
    business_value: str
    api_endpoint: str
    display: str = "kpi"


class DashboardProvenance(BaseModel):
    dedupe_strategy: str
    data_confidence: str
    feed_status: str
    last_event_at: datetime | None = None
    pipeline_events: int = 0
    zones_tracked: int = 0
    layout_mapped: bool = False
    detector_mode: str | None = None
    source_videos: list[str] = Field(default_factory=list)
    processing_lineage: str | None = None


class DashboardReviewerEvidence(BaseModel):
    """Pipeline ingestion proof for Purple Tech evaluators."""

    videos_processed: int = 0
    source_videos: list[str] = Field(default_factory=list)
    frames_analyzed: int = 0
    events_generated: int = 0
    last_ingestion_at: datetime | None = None
    detector_mode: str | None = None
    processing_lineage: str | None = None
    detection_evidence: str | None = None


class ReviewerHeadline(BaseModel):
    """Top-line metrics evaluators should see within 10 minutes."""

    cctv_videos: str = "0/5"
    vision_events: int = 0
    entries: int = 0
    exits: int = 0
    re_entries: int = 0
    unique_visitors: int = 0
    funnel_purchase: int = 0
    pos_purchases: int = 0
    pos_revenue_inr: float = 0.0
    linked_purchases: int = 0
    feed_status: str = "unknown"
    feed_note: str | None = None
    footnotes: list[str] = Field(default_factory=list)


class StoreDashboardSummaryResponse(BaseModel):
    store_id: UUID
    period_start: datetime
    period_end: datetime
    last_refreshed_at: datetime
    refresh_interval_seconds: int = 5
    kpis: list[DashboardKpiCard]
    reviewer_evidence: DashboardReviewerEvidence
    reviewer_headline: ReviewerHeadline
    provenance: DashboardProvenance
    funnel_stages: list[FunnelStageResult] = Field(default_factory=list)
    pos_insights: PosInsights | None = None
    meta: PaginatedMeta = Field(default_factory=PaginatedMeta)
