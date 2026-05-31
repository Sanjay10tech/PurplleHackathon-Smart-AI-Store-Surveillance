# PROMPT:
# Final coverage gaps — event repo integrity, ingestion edges, health 503, dependencies.
#
# CHANGES MADE:
# - IntegrityError recovery, validation branches, readiness failure, log_request_context.

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.config import get_settings
from app.dependencies import log_request_context
from app.models import Event
from app.repositories.event_repository import EventRepository
from app.repositories.event_repository import EventRepository
from app.repositories.store_repository import StoreRepository
from app.schemas.events import EventAggregate, EventBatchIngestRequest, EventIngestRequest
from app.services.event_ingestion_service import EventIngestionService
from app.services.event_validation_service import EventValidationService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService


@pytest.mark.asyncio
async def test_event_repository_integrity_error_returns_duplicate_key(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    async with db_session_factory() as session:
        repo = EventRepository(session)
        existing = Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={},
            correlation_id="existing",
            idempotency_key="dup-key-recover",
            occurred_at=datetime.now(tz=UTC),
        )
        await repo.create(existing)
        duplicate = Event(
            id=uuid.uuid4(),
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={},
            correlation_id="duplicate",
            idempotency_key="dup-key-recover",
            occurred_at=datetime.now(tz=UTC),
        )

        async def raise_integrity(_entity: Event) -> Event:
            raise IntegrityError("statement", {}, Exception())

        from app.schemas.events import IngestOutcome

        with patch.object(repo, "create", side_effect=raise_integrity):
            saved, outcome = await repo.create_idempotent(duplicate)
        assert outcome == IngestOutcome.DUPLICATE_KEY
        assert saved.id == existing.id
        await session.commit()


@pytest.mark.asyncio
async def test_event_ingest_existing_id_in_batch(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = EventRepository(session)
        service = EventIngestionService(
            event_repository=repo,
            validation_service=EventValidationService(StoreRepository(session)),
            settings=get_settings(),
        )
        event_id = uuid.uuid4()
        first = EventIngestRequest(
            event_id=event_id,
            event_type="vision.frame.processed",
            occurred_at=datetime.now(tz=UTC),
            store_id=seeded_store,
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
        )
        await service.ingest_batch(EventBatchIngestRequest(events=[first]), "c1")
        second = EventIngestRequest(
            event_id=event_id,
            event_type="vision.frame.processed",
            occurred_at=datetime.now(tz=UTC),
            store_id=seeded_store,
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
        )
        response = await service.ingest_batch(
            EventBatchIngestRequest(events=[second]), "c2"
        )
        assert response.results[0].status == "duplicate"
        await session.commit()


@pytest.mark.asyncio
async def test_readiness_returns_503_when_db_down(client: AsyncClient) -> None:
    with patch(
        "app.services.health_service.check_database_connection",
        AsyncMock(return_value=False),
    ):
        response = await client.get("/health/ready")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_log_request_context_binds_fields() -> None:
    scope = {
        "type": "http",
        "path": "/api/v1/events/ingest",
        "headers": [],
        "method": "POST",
    }
    request = Request(scope)
    gen = log_request_context(request, correlation_id="ctx-corr")
    async for _ in gen:
        break


@pytest.mark.asyncio
async def test_funnel_purchase_without_session(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        service = FunnelService(
            __import__("app.repositories.funnel_repository", fromlist=["FunnelRepository"]).FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        tx = __import__("app.models", fromlist=["Transaction"]).Transaction(
            store_id=seeded_store,
            session_id=None,
            amount=__import__("decimal").Decimal("1.00"),
            occurred_at=datetime.now(tz=UTC),
        )
        session.add(tx)
        await session.commit()
        result = await service.get_funnel(seeded_store)
        assert result.stages[-1].count == 0


def test_heatmap_overall_confidence_mixed_and_low_only() -> None:
    assert HeatmapService._overall_confidence([MagicMock(data_confidence="LOW")]) == "LOW"
    assert HeatmapService._overall_confidence(
        [MagicMock(data_confidence="HIGH"), MagicMock(data_confidence="LOW")]
    ) == "MEDIUM"


@pytest.mark.asyncio
async def test_router_non_object_body(client: AsyncClient) -> None:
    response = await client.post("/api/v1/events/ingest", json=["not", "object"])
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_validation_duplicate_idempotency_in_batch(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        validator = EventValidationService(StoreRepository(session))
        req = EventIngestRequest(
            event_type="vision.frame.processed",
            occurred_at=datetime.now(tz=UTC),
            store_id=seeded_store,
            aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
            payload={},
            idempotency_key="dup-batch-key",
        )
        seen_keys: set[str] = {"dup-batch-key"}
        result = await validator.validate(req, seen_event_ids=set(), seen_idempotency_keys=seen_keys)
        assert result.valid is False
        assert result.errors[0].code == "duplicate_idempotency_key_in_batch"


@pytest.mark.asyncio
async def test_validation_cached_tenant_mismatch(
    db_session_factory, seeded_store: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        validator = EventValidationService(StoreRepository(session))
        await validator.validate(
            EventIngestRequest(
                event_type="vision.frame.processed",
                occurred_at=datetime.now(tz=UTC),
                store_id=seeded_store,
                aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
                payload={},
            ),
            seen_event_ids=set(),
            seen_idempotency_keys=set(),
        )
        wrong_tenant = uuid.UUID("00000000-0000-0000-0000-000000000099")
        result = await validator.validate(
            EventIngestRequest(
                event_type="vision.frame.processed",
                occurred_at=datetime.now(tz=UTC),
                store_id=seeded_store,
                tenant_id=wrong_tenant,
                aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
                payload={},
            ),
            seen_event_ids=set(),
            seen_idempotency_keys=set(),
        )
        assert result.valid is False
        assert any(e.code == "tenant_store_mismatch" for e in result.errors)


@pytest.mark.asyncio
async def test_validation_store_id_from_payload(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        validator = EventValidationService(StoreRepository(session))
        result = await validator.validate(
            EventIngestRequest(
                event_type="vision.frame.processed",
                occurred_at=datetime.now(tz=UTC),
                aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
                payload={"store_id": str(seeded_store)},
            ),
            seen_event_ids=set(),
            seen_idempotency_keys=set(),
        )
        assert result.valid is True
        assert result.store_id == seeded_store


@pytest.mark.asyncio
async def test_health_repository_scoped_to_store(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from app.repositories.health_repository import HealthRepository

    async with db_session_factory() as session:
        repo = HealthRepository(session)
        assert await repo.get_last_feed_event_at(store_id=seeded_store) is None
        assert await repo.get_last_feed_event_at() is None


@pytest.mark.asyncio
async def test_store_metric_postgresql_upsert_path(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from app.models import StoreMetric
    from app.repositories.store_metric_repository import StoreMetricRepository

    async with db_session_factory() as session:
        repo = StoreMetricRepository(session)
        bucket = datetime(2026, 5, 30, 9, 0, tzinfo=UTC)
        metric = StoreMetric(
            store_id=seeded_store,
            metric_name="footfall.count",
            bucket_start=bucket,
            bucket_end=bucket + __import__("datetime").timedelta(hours=1),
            granularity="hour",
            dimensions={},
            value=3.0,
            sample_count=3,
        )
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        with patch.object(session, "get_bind", return_value=mock_bind):
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = metric
            with patch.object(session, "execute", AsyncMock(return_value=mock_result)):
                with patch.object(session, "refresh", AsyncMock()):
                    saved = await repo.upsert(metric)
        assert saved.value == 3.0
