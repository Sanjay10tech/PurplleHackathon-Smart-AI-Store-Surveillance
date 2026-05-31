from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HeatmapZoneCell(BaseModel):
    zone_key: str
    zone_label: str
    visit_count: int
    avg_dwell_seconds: float | None = None
    dwell_sample_count: int = 0
    normalized_visit_score: float = 0.0
    normalized_dwell_score: float = 0.0
    data_confidence: str = "LOW"
    layout_section: str | None = None


class StoreHeatmapResponse(BaseModel):
    store_id: UUID
    period_start: datetime
    period_end: datetime
    zones: list[HeatmapZoneCell]
    meta: dict[str, Any] = Field(default_factory=dict)
