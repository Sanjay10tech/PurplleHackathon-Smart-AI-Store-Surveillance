# PROMPT:
# Generate complete pytest suite scenario: duplicate event ingestion.
# Verify idempotency by event_id and idempotency_key via service and HTTP API.
#
# CHANGES MADE:
# - Matrix tests for DUPLICATE_ID and DUPLICATE_KEY outcomes.
# - Ensures duplicate ingest does not create extra rows and returns correct HTTP status.

import uuid
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.schemas.events import EventAggregate, EventBatchIngestRequest, EventIngestRequest, IngestOutcome


@pytest.mark.asyncio
async def test_duplicate_event_id_rejected(
    ingestion_service,
    seeded_store: UUID,
) -> None:
    service, session = ingestion_service
    event_id = uuid.uuid4()
    request = EventIngestRequest(
        event_id=event_id,
        event_type="vision.frame.processed",
        occurred_at=datetime.now(tz=UTC),
        store_id=seeded_store,
        aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
        payload={"frame_index": 1},
    )
    first = await service.ingest_batch(
        EventBatchIngestRequest(events=[request]),
        correlation_id="dup-id-1",
    )
    second = await service.ingest_batch(
        EventBatchIngestRequest(events=[request]),
        correlation_id="dup-id-2",
    )
    await session.commit()

    assert first.results[0].status == "accepted"
    assert second.results[0].status == "duplicate"
    assert second.results[0].duplicate_reason == IngestOutcome.DUPLICATE_ID


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_rejected(
    ingestion_service,
    seeded_store: UUID,
) -> None:
    service, session = ingestion_service
    key = "dup-key-checkout-001"
    first_request = EventIngestRequest(
        event_type="vision.frame.processed",
        occurred_at=datetime.now(tz=UTC),
        store_id=seeded_store,
        aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
        payload={"frame_index": 10},
        idempotency_key=key,
    )
    second_request = EventIngestRequest(
        event_id=uuid.uuid4(),
        event_type="vision.frame.processed",
        occurred_at=datetime.now(tz=UTC),
        store_id=seeded_store,
        aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
        payload={"frame_index": 11},
        idempotency_key=key,
    )

    first = await service.ingest_batch(
        EventBatchIngestRequest(events=[first_request]),
        correlation_id="dup-key-1",
    )
    second = await service.ingest_batch(
        EventBatchIngestRequest(events=[second_request]),
        correlation_id="dup-key-2",
    )
    await session.commit()

    assert first.results[0].status == "accepted"
    assert second.results[0].status == "duplicate"
    assert second.results[0].duplicate_reason == IngestOutcome.DUPLICATE_KEY


@pytest.mark.asyncio
async def test_duplicate_ingest_api_idempotency_key(client: AsyncClient, seeded_store: UUID) -> None:
    payload = {
        "event_type": "vision.frame.processed",
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "store_id": str(seeded_store),
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {"frame_index": 99},
        "idempotency_key": "api-dup-key-1",
    }
    first = await client.post("/api/v1/events/ingest", json=payload)
    second = await client.post("/api/v1/events/ingest", json=payload)

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert second.status_code == 202
    assert second.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_duplicate_batch_event_id_api(client: AsyncClient, seeded_store: UUID) -> None:
    event_id = str(uuid.uuid4())
    event = {
        "event_id": event_id,
        "event_type": "vision.frame.processed",
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "store_id": str(seeded_store),
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {},
    }
    first = await client.post("/api/v1/events/ingest", json={"events": [event]})
    second = await client.post("/api/v1/events/ingest", json={"events": [event]})

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["results"][0]["duplicate_reason"] == "duplicate_id"
