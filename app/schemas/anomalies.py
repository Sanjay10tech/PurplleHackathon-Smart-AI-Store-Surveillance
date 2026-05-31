from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AnomalyItem(BaseModel):
    id: UUID
    anomaly_type: str
    severity: str
    detected_at: datetime
    message: str
    suggested_action: str
    context: dict[str, Any] = Field(default_factory=dict)
    source: str = "computed"


class StoreAnomaliesResponse(BaseModel):
    store_id: UUID
    period_start: datetime
    period_end: datetime
    items: list[AnomalyItem]
    meta: dict[str, Any] = Field(default_factory=dict)
