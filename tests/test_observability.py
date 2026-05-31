# PROMPT:
# Generate complete pytest suite — observability health service, trace headers, and structured logs.
#
# CHANGES MADE:
# - HealthService fresh/stale/DB-down paths, /health enrichment, and middleware log fields.

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.models import Event
from app.repositories.health_repository import HealthRepository
from app.services.health_service import HealthService


class TestObservabilityContext:
    def test_extract_store_id_from_path(self) -> None:
        from app.observability.context import extract_store_id_from_path

        store_id = "00000000-0000-0000-0000-000000000101"
        path = f"/api/v1/stores/{store_id}/metrics"
        assert extract_store_id_from_path(path) == store_id
        assert extract_store_id_from_path("/health") is None


class TestHealthService:
    @pytest.mark.asyncio
    async def test_health_ok_with_fresh_feed(self, db_session_factory) -> None:
        store_id = uuid.uuid4()
        async with db_session_factory() as session:
            session.add(
                Event(
                    store_id=store_id,
                    tenant_id=uuid.uuid4(),
                    event_type="vision.frame.processed",
                    schema_version="1.0.0",
                    aggregate_type="pipeline_run",
                    aggregate_id=uuid.uuid4(),
                    payload={},
                    correlation_id="h1",
                    occurred_at=datetime.now(tz=UTC) - timedelta(minutes=2),
                )
            )
            await session.commit()

            service = HealthService(
                health_repository=HealthRepository(session),
                settings=Settings(health_stale_feed_minutes=15),
            )
            with patch(
                "app.services.health_service.check_database_connection",
                AsyncMock(return_value=True),
            ):
                body, status_code = await service.get_health()

        assert status_code == 200
        assert body.status == "ok"
        assert body.checks.database == "up"
        assert body.checks.feed == "fresh"
        assert body.stale_feed is False
        assert body.last_event_at is not None

    @pytest.mark.asyncio
    async def test_health_degraded_stale_feed(self, db_session_factory) -> None:
        store_id = uuid.uuid4()
        async with db_session_factory() as session:
            session.add(
                Event(
                    store_id=store_id,
                    tenant_id=uuid.uuid4(),
                    event_type="vision.zone.entered",
                    schema_version="1.0.0",
                    aggregate_type="zone",
                    aggregate_id=uuid.uuid4(),
                    payload={"zone_type": "browse"},
                    correlation_id="h2",
                    occurred_at=datetime.now(tz=UTC) - timedelta(minutes=30),
                )
            )
            await session.commit()

            service = HealthService(
                health_repository=HealthRepository(session),
                settings=Settings(health_stale_feed_minutes=15),
            )
            with patch(
                "app.services.health_service.check_database_connection",
                AsyncMock(return_value=True),
            ):
                body, status_code = await service.get_health()

        assert status_code == 200
        assert body.status == "degraded"
        assert body.stale_feed is True
        assert body.checks.feed == "stale"
        assert body.feed_stale_minutes is not None
        assert body.feed_stale_minutes >= 15

    @pytest.mark.asyncio
    async def test_health_unhealthy_database_down(self, db_session_factory) -> None:
        async with db_session_factory() as session:
            service = HealthService(
                health_repository=HealthRepository(session),
                settings=Settings(),
            )
            with patch(
                "app.services.health_service.check_database_connection",
                AsyncMock(return_value=False),
            ):
                body, status_code = await service.get_health()

        assert status_code == 503
        assert body.status == "unhealthy"
        assert body.checks.database == "down"


@pytest.mark.asyncio
async def test_health_endpoint_enriched(client: AsyncClient, mock_db_check: None) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "store-intelligence-api"
    assert "checks" in body
    assert body["checks"]["database"] == "up"
    assert "stale_feed" in body
    assert "last_event_at" in body


@pytest.mark.asyncio
async def test_health_stale_feed_with_old_event(
    client: AsyncClient,
    db_session_factory,
    seeded_store: uuid.UUID,
) -> None:
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    async with db_session_factory() as session:
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=tenant_id,
                event_type="vision.frame.processed",
                schema_version="1.0.0",
                aggregate_type="pipeline_run",
                aggregate_id=uuid.uuid4(),
                payload={"frame_index": 1},
                correlation_id="stale1",
                occurred_at=datetime.now(tz=UTC) - timedelta(hours=2),
            )
        )
        await session.commit()

    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["stale_feed"] is True
    assert body["checks"]["feed"] == "stale"


@pytest.mark.asyncio
async def test_trace_id_header_propagated(client: AsyncClient) -> None:
    trace_id = "trace-test-12345"
    response = await client.get("/health", headers={"X-Trace-ID": trace_id})
    assert response.status_code == 200
    assert response.headers.get("X-Trace-ID") == trace_id
    assert response.headers.get("X-Correlation-ID") == trace_id


@pytest.mark.asyncio
async def test_middleware_logs_structured_fields(
    client: AsyncClient,
    seeded_store: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/metrics")
    assert response.status_code == 200

    output = capsys.readouterr().out
    assert "http_request_completed" in output
    assert "trace_id=" in output
    assert "endpoint=" in output
    assert "latency_ms=" in output
    assert "status_code=200" in output
    assert str(seeded_store) in output
    assert "event_count=0" in output


@pytest.mark.asyncio
async def test_ingest_sets_event_count_in_logs(
    client: AsyncClient,
    seeded_store: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "event_type": "vision.frame.processed",
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "store_id": str(seeded_store),
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {"frame_index": 99},
        "idempotency_key": "obs-event-count",
    }
    response = await client.post("/api/v1/events/ingest", json=payload)
    assert response.status_code == 202

    output = capsys.readouterr().out
    assert "http_request_completed" in output
    assert "event_count=1" in output
    assert str(seeded_store) in output
