from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class FunnelStageResult(BaseModel):
    stage: str
    count: int
    conversion_rate: float | None = None
    drop_off_rate: float | None = None
    re_entry_count: int = 0


class StoreFunnelResponse(BaseModel):
    store_id: UUID
    period_start: datetime
    period_end: datetime
    unique_visitors: int = 0
    dedupe_strategy: str = "session_id"
    stages: list[FunnelStageResult]
    meta: dict[str, Any] = Field(default_factory=dict)
