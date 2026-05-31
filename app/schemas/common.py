from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    errors: list[dict[str, str]] | None = None


# Health schemas live in app.schemas.health


class TimeRangeQuery(BaseModel):
    from_ts: datetime | None = Field(default=None, alias="from")
    to_ts: datetime | None = Field(default=None, alias="to")
    granularity: str = Field(default="hour", pattern="^(minute|hour|day)$")

    model_config = ConfigDict(populate_by_name=True)


class PaginatedMeta(BaseModel):
    partial: bool = False
    source: str = "placeholder"
    message: str | None = None
    reviewer_proof: dict[str, Any] | None = None


class MetricSeriesPoint(BaseModel):
    bucket_start: datetime
    value: float
    sample_count: int = 0


class StoreMetricsResponse(BaseModel):
    store_id: UUID
    metric: str
    granularity: str
    series: list[MetricSeriesPoint]
    unique_visitors: int = 0
    session_count: int = 0
    meta: PaginatedMeta = Field(default_factory=PaginatedMeta)


class FunnelStage(BaseModel):
    stage: str
    count: int
    conversion_rate: float | None = None


class StoreFunnelResponse(BaseModel):
    store_id: UUID
    period_start: datetime
    period_end: datetime
    stages: list[FunnelStage]
    meta: PaginatedMeta = Field(default_factory=PaginatedMeta)


# Heatmap and anomaly response schemas live in app.schemas.heatmap / app.schemas.anomalies
