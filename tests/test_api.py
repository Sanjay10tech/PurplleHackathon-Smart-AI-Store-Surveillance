# PROMPT:
# Generate complete pytest suite — core API smoke tests for health, ingest, metrics, and 404 handling.
#
# CHANGES MADE:
# - Validates /health enriched payload, single-event ingest idempotency, and store-not-found errors.

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient, mock_db_check: None) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["service"] == "store-intelligence-api"
    assert body["checks"]["database"] == "up"
    assert "stale_feed" in body


@pytest.mark.asyncio
async def test_readiness(client: AsyncClient, mock_db_check: None) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ingest_event(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    payload = {
        "event_type": "vision.frame.processed",
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "store_id": str(seeded_store),
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {"store_id": str(seeded_store), "frame_index": 1},
        "idempotency_key": "test-frame-1",
    }
    response = await client.post("/api/v1/events/ingest", json=payload)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["duplicate"] is False

    duplicate = await client.post("/api/v1/events/ingest", json=payload)
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_store_metrics_placeholder(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == str(seeded_store)
    assert body["meta"]["source"] == "placeholder"


@pytest.mark.asyncio
async def test_store_not_found(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    response = await client.get(f"/api/v1/stores/{missing}/metrics")
    assert response.status_code == 404
