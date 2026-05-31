from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class JourneyStageRecord(BaseModel):
    stage: str
    occurred_at: datetime | None = None
    source: str = "cctv"


class JourneyPurchaseRecord(BaseModel):
    transaction_id: UUID
    invoice_number: str
    order_id: str
    amount: Decimal
    currency: str = "INR"
    occurred_at: datetime
    link_method: str | None = None
    link_confidence: float | None = None


class RetailJourney(BaseModel):
    visitor_key: str
    external_track_id: str | None = None
    stages: list[JourneyStageRecord]
    zones_visited: list[str] = Field(default_factory=list)
    purchase: JourneyPurchaseRecord | None = None
    complete: bool = False
    stage_count: int = 0


class StoreRetailJourneysResponse(BaseModel):
    store_id: UUID
    period_start: datetime
    period_end: datetime
    journeys: list[RetailJourney]
    meta: dict[str, Any] = Field(default_factory=dict)
