# PROMPT:
# Ingestion and router branch coverage — invalid JSON, persistence errors, HTTP status paths.
#
# CHANGES MADE:
# - Single-event ValidationError, DB failure handling, router 422 batch-too-large, schema validation.

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.exceptions import ValidationError
from app.repositories.event_repository import EventRepository
from app.repositories.store_repository import StoreRepository
from app.schemas.events import EventAggregate, EventBatchIngestRequest, EventIngestRequest, MAX_BATCH_SIZE
from app.services.event_ingestion_service import EventIngestionService
from app.services.event_validation_service import EventValidationService


def _valid_event(store_id: uuid.UUID) -> EventIngestRequest:
    return EventIngestRequest(
        event_id=uuid.uuid4(),
        event_type="vision.frame.processed",
        occurred_at=datetime.now(tz=UTC),
        store_id=store_id,
        aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
        payload={},
    )


@pytest.mark.asyncio
async def test_single_ingest_raises_on_rejection(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        service = EventIngestionService(
            event_repository=EventRepository(session),
            validation_service=EventValidationService(StoreRepository(session)),
            settings=get_settings(),
        )
        bad = EventIngestRequest(
            event_type="invalid.prefix",
            occurred_at=datetime.now(tz=UTC),
            store_id=seeded_store,
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
        )
        with pytest.raises(ValidationError):
            await service.ingest(bad, correlation_id="single-bad")


@pytest.mark.asyncio
async def test_ingest_persistence_error_returns_rejected(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = EventRepository(session)
        service = EventIngestionService(
            event_repository=repo,
            validation_service=EventValidationService(StoreRepository(session)),
            settings=get_settings(),
        )
        with patch.object(repo, "create_idempotent", AsyncMock(side_effect=RuntimeError("db fail"))):
            response = await service.ingest_batch(
                EventBatchIngestRequest(events=[_valid_event(seeded_store)]),
                correlation_id="persist-fail",
            )
        assert response.summary.rejected == 1
        assert response.results[0].errors[0].code == "persistence_error"


@pytest.mark.asyncio
async def test_router_rejects_invalid_json(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/events/ingest",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_router_batch_too_large_problem_detail(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    events = [
        {
            "event_type": "vision.frame.processed",
            "occurred_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "store_id": str(seeded_store),
            "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
            "payload": {},
        }
        for _ in range(MAX_BATCH_SIZE + 1)
    ]
    response = await client.post("/api/v1/events/ingest", json={"events": events})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "batch-too-large" in response.json()["type"]


def test_schema_version_validator_rejects_bad_semver() -> None:
    with pytest.raises(ValueError):
        EventIngestRequest(
            event_type="vision.frame.processed",
            schema_version="not-semver",
            occurred_at=datetime.now(tz=UTC),
            store_id=uuid.uuid4(),
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
        )
