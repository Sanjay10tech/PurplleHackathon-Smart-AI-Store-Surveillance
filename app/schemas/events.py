from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_BATCH_SIZE = 500

ALLOWED_EVENT_PREFIXES = ("ingestion.", "vision.", "analytics.")


class EventAggregate(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    id: UUID


class EventIngestRequest(BaseModel):
    """Single inbound domain event."""

    event_id: UUID | None = Field(
        default=None,
        description="Client-assigned UUID; deduplicated on ingest",
    )
    event_type: str = Field(..., min_length=3, max_length=128, examples=["vision.frame.processed"])
    schema_version: str = Field(default="1.0.0", max_length=16)
    tenant_id: UUID | None = Field(
        default=None,
        description="Optional; resolved from store when omitted",
    )
    store_id: UUID | None = Field(
        default=None,
        description="Used to resolve tenant when tenant_id omitted",
    )
    occurred_at: datetime
    correlation_id: str | None = Field(default=None, max_length=64)
    causation_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=256)
    aggregate: EventAggregate
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("schema_version")
    @classmethod
    def schema_version_semver(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) < 2 or not all(p.isdigit() for p in parts):
            raise ValueError("schema_version must be semver (e.g. 1.0.0)")
        return v


class EventBatchIngestRequest(BaseModel):
    """Batch ingest envelope — up to 500 events per request."""

    events: list[EventIngestRequest] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)

    model_config = ConfigDict(extra="forbid")


class IngestItemError(BaseModel):
    code: str
    message: str
    field: str | None = None


class IngestOutcome(str, Enum):
    CREATED = "created"
    DUPLICATE_ID = "duplicate_id"
    DUPLICATE_KEY = "duplicate_key"


class EventIngestItemResult(BaseModel):
    index: int
    event_id: UUID | None = None
    event_type: str | None = None
    status: Literal["accepted", "duplicate", "rejected"]
    duplicate_reason: IngestOutcome | None = None
    correlation_id: str | None = None
    errors: list[IngestItemError] = Field(default_factory=list)


class BatchIngestSummary(BaseModel):
    total: int
    accepted: int
    duplicate: int
    rejected: int


class EventBatchIngestResponse(BaseModel):
    correlation_id: str
    summary: BatchIngestSummary
    results: list[EventIngestItemResult]


class EventIngestResponse(BaseModel):
    """Single-event response (backward compatible)."""

    event_id: UUID
    event_type: str
    status: Literal["accepted", "duplicate"] = "accepted"
    duplicate: bool = False
    duplicate_reason: IngestOutcome | None = None
    correlation_id: str
