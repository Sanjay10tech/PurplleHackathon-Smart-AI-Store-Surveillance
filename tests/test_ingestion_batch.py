# PROMPT:
# Generate complete pytest suite — batch ingestion partial success, deduplication, and HTTP status codes.
#
# CHANGES MADE:
# - Service-level batch validation tests and API tests for 202/207/422 responses.

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.repositories.event_repository import EventRepository
from app.repositories.store_repository import StoreRepository
from app.schemas.events import EventAggregate, EventBatchIngestRequest, EventIngestRequest, IngestOutcome
from app.services.event_ingestion_service import EventIngestionService
from app.services.event_validation_service import EventValidationService


@pytest.mark.asyncio
async def test_batch_partial_success(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        service = EventIngestionService(
            event_repository=EventRepository(session),
            validation_service=EventValidationService(StoreRepository(session)),
            settings=get_settings(),
        )
        good = EventIngestRequest(
            event_id=uuid.uuid4(),
            event_type="vision.frame.processed",
            occurred_at=datetime.now(tz=UTC),
            store_id=seeded_store,
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
            idempotency_key="batch-ok-1",
        )
        bad = EventIngestRequest(
            event_type="bad.type",
            occurred_at=datetime.now(tz=UTC),
            store_id=seeded_store,
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
        )
        response = await service.ingest_batch(
            EventBatchIngestRequest(events=[good, bad]),
            correlation_id="batch-corr-1",
        )
        assert response.summary.total == 2
        assert response.summary.accepted == 1
        assert response.summary.rejected == 1
        assert response.results[0].status == "accepted"
        assert response.results[1].status == "rejected"
        assert response.results[1].errors[0].code == "invalid_event_type"
        await session.commit()


@pytest.mark.asyncio
async def test_deduplicate_by_event_id(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        service = EventIngestionService(
            event_repository=EventRepository(session),
            validation_service=EventValidationService(StoreRepository(session)),
            settings=get_settings(),
        )
        event_id = uuid.uuid4()
        request = EventIngestRequest(
            event_id=event_id,
            event_type="vision.frame.processed",
            occurred_at=datetime.now(tz=UTC),
            store_id=seeded_store,
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
        )
        first = await service.ingest_batch(
            EventBatchIngestRequest(events=[request]),
            correlation_id="c1",
        )
        assert first.results[0].status == "accepted"

        second = await service.ingest_batch(
            EventBatchIngestRequest(events=[request]),
            correlation_id="c2",
        )
        assert second.results[0].status == "duplicate"
        assert second.results[0].duplicate_reason == IngestOutcome.DUPLICATE_ID
        await session.commit()


@pytest.mark.asyncio
async def test_batch_api_returns_207(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    event_id = uuid.uuid4()
    payload = {
        "events": [
            {
                "event_id": str(event_id),
                "event_type": "vision.frame.processed",
                "occurred_at": datetime.now(tz=UTC).isoformat(),
                "store_id": str(seeded_store),
                "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
                "payload": {},
            },
            {
                "event_type": "not.valid",
                "occurred_at": datetime.now(tz=UTC).isoformat(),
                "store_id": str(seeded_store),
                "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
                "payload": {},
            },
        ]
    }
    response = await client.post("/api/v1/events/ingest", json=payload)
    assert response.status_code == 207
    body = response.json()
    assert body["summary"]["accepted"] == 1
    assert body["summary"]["rejected"] == 1


@pytest.mark.asyncio
async def test_batch_api_rejects_over_500(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    events = [
        {
            "event_type": "vision.frame.processed",
            "occurred_at": datetime.now(tz=UTC).isoformat(),
            "store_id": str(seeded_store),
            "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
            "payload": {},
            "idempotency_key": f"k-{i}",
        }
        for i in range(501)
    ]
    response = await client.post("/api/v1/events/ingest", json={"events": events})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_single_ingest_still_works(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    payload = {
        "event_type": "vision.frame.processed",
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "store_id": str(seeded_store),
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {"frame_index": 1},
        "idempotency_key": "single-key-1",
    }
    response = await client.post("/api/v1/events/ingest", json=payload)
    assert response.status_code == 202
    assert response.json()["duplicate"] is False
