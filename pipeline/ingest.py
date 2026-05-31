"""Connect pipeline event output to FastAPI POST /api/v1/events/ingest."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.events import EventBatchIngestRequest, EventIngestRequest, MAX_BATCH_SIZE
from app.services.event_ingestion_service import EventIngestionService
from pipeline.tracker import SessionRecord

DEFAULT_INGEST_PATH = "/api/v1/events/ingest"


def validate_event_dict(event: dict[str, Any]) -> EventIngestRequest:
    """Raise pydantic ValidationError if event is not ingest-ready."""
    return EventIngestRequest.model_validate(event)


def validate_event_dicts(events: list[dict[str, Any]]) -> tuple[list[EventIngestRequest], list[str]]:
    """Validate a list of raw pipeline events; return (valid, error_messages)."""
    validated: list[EventIngestRequest] = []
    errors: list[str] = []
    for index, raw in enumerate(events):
        try:
            validated.append(validate_event_dict(raw))
        except PydanticValidationError as exc:
            errors.append(f"event[{index}]: {exc.errors()[0]['msg']}")
    return validated, errors


def partition_batches(events: list[dict[str, Any]], batch_size: int = MAX_BATCH_SIZE) -> list[list[dict[str, Any]]]:
    size = max(1, min(batch_size, MAX_BATCH_SIZE))
    return [events[i : i + size] for i in range(0, len(events), size)]


class PipelineIngestClient:
    """HTTP client for batch ingestion into the FastAPI events API."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8000",
        ingest_path: str = DEFAULT_INGEST_PATH,
        batch_size: int = 100,
        timeout_seconds: float = 120.0,
        validate_before_post: bool = True,
        api_key: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ingest_path = ingest_path if ingest_path.startswith("/") else f"/{ingest_path}"
        self._batch_size = max(1, min(batch_size, MAX_BATCH_SIZE))
        self._timeout = timeout_seconds
        self._validate = validate_before_post
        self._headers = {"X-API-Key": api_key} if api_key else {}

    @property
    def ingest_url(self) -> str:
        return f"{self._base_url}{self._ingest_path}"

    async def ingest_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {"posted": 0, "accepted": 0, "rejected": 0, "duplicate": 0, "batches": 0}

        if self._validate:
            _, validation_errors = validate_event_dicts(events)
            if validation_errors:
                raise ValueError("Event validation failed: " + "; ".join(validation_errors))

        summary = {"posted": 0, "accepted": 0, "rejected": 0, "duplicate": 0, "batches": 0}

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, headers=self._headers) as client:
            for batch in partition_batches(events, self._batch_size):
                summary["batches"] += 1
                if len(batch) == 1:
                    resp = await client.post(self._ingest_path, json=batch[0])
                    summary["posted"] += 1
                    _tally_http_response(resp, summary, batch_size=1)
                    continue

                resp = await client.post(self._ingest_path, json={"events": batch})
                summary["posted"] += len(batch)
                _tally_http_response(resp, summary, batch_size=len(batch))

        return summary

    def ingest_events_sync(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        return asyncio.run(self.ingest_events(events))


def _tally_http_response(resp: httpx.Response, summary: dict[str, Any], *, batch_size: int) -> None:
    if resp.status_code in (200, 201, 202):
        body = resp.json()
        if "summary" in body:
            batch_summary = body["summary"]
            summary["accepted"] += int(batch_summary.get("accepted", 0))
            summary["rejected"] += int(batch_summary.get("rejected", 0))
            summary["duplicate"] += int(batch_summary.get("duplicate", 0))
        elif body.get("duplicate"):
            summary["duplicate"] += 1
        else:
            summary["accepted"] += 1
        return

    if resp.status_code == 207:
        body = resp.json()
        batch_summary = body.get("summary", {})
        summary["accepted"] += int(batch_summary.get("accepted", 0))
        summary["rejected"] += int(batch_summary.get("rejected", 0))
        summary["duplicate"] += int(batch_summary.get("duplicate", 0))
        return

    summary["rejected"] += batch_size


async def ingest_via_service(
    service: EventIngestionService,
    events: list[dict[str, Any]],
    correlation_id: str,
    *,
    validate: bool = True,
) -> Any:
    """In-process batch ingest (used by integration tests without HTTP)."""
    if validate:
        validated, errors = validate_event_dicts(events)
        if errors:
            raise ValueError("Event validation failed: " + "; ".join(errors))
    else:
        validated = [EventIngestRequest.model_validate(e) for e in events]

    return await service.ingest_batch(
        EventBatchIngestRequest(events=validated),
        correlation_id,
    )


async def persist_sessions_to_db(db: AsyncSession, sessions: list[SessionRecord]) -> int:
    """Write pipeline session records so funnel/metrics can resolve session_id on events."""
    from datetime import UTC

    from app.models import VisitSession

    count = 0
    for rec in sessions:
        db.add(
            VisitSession(
                id=rec.session_id,
                store_id=UUID(rec.store_id),
                external_track_id=rec.external_track_id,
                status=rec.status,
                started_at=rec.started_at.replace(tzinfo=UTC)
                if rec.started_at.tzinfo is None
                else rec.started_at,
                ended_at=(
                    rec.ended_at.replace(tzinfo=UTC)
                    if rec.ended_at and rec.ended_at.tzinfo is None
                    else rec.ended_at
                ),
                metadata_=rec.metadata,
            )
        )
        count += 1
    return count
