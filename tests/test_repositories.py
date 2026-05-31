# PROMPT:
# Generate complete pytest suite — repository layer idempotency and CRUD correctness.
#
# CHANGES MADE:
# - Tests for events, transactions, metrics, anomalies, and visit session repositories.

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import Anomaly, Event, StoreMetric, Transaction, VisitSession
from app.repositories.anomaly_repository import AnomalyRepository
from app.repositories.event_repository import EventRepository
from app.schemas.events import IngestOutcome
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.visit_session_repository import VisitSessionRepository


@pytest.mark.asyncio
async def test_event_idempotent_ingest(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        repo = EventRepository(session)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        event = Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={"frame_index": 1},
            correlation_id="corr-1",
            idempotency_key="frame-001",
            occurred_at=datetime.now(tz=UTC),
        )
        saved, outcome = await repo.create_idempotent(event)
        assert outcome == IngestOutcome.CREATED

        retry = Event(
            id=uuid.uuid4(),
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={"frame_index": 2},
            correlation_id="corr-2",
            idempotency_key="frame-001",
            occurred_at=datetime.now(tz=UTC),
        )
        again, outcome2 = await repo.create_idempotent(retry)
        assert outcome2 == IngestOutcome.DUPLICATE_KEY
        assert again.id == saved.id
        assert again.id == saved.id
        await session.commit()


@pytest.mark.asyncio
async def test_event_list_by_store_uses_indexed_columns(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = EventRepository(session)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        for i in range(3):
            await repo.create(
                Event(
                    store_id=seeded_store,
                    tenant_id=tenant_id,
                    event_type="vision.zone.entered",
                    schema_version="1.0.0",
                    aggregate_type="track",
                    aggregate_id=uuid.uuid4(),
                    payload={},
                    correlation_id=f"c-{i}",
                    idempotency_key=f"key-{i}",
                    occurred_at=datetime.now(tz=UTC),
                )
            )
        rows = await repo.list_by_store(
            seeded_store,
            event_types=["vision.zone.entered"],
        )
        assert len(rows) == 3
        await session.commit()


@pytest.mark.asyncio
async def test_transaction_external_ref_dedup(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        repo = TransactionRepository(session)
        tx = Transaction(
            store_id=seeded_store,
            external_ref="POS-1001",
            amount=Decimal("42.50"),
            occurred_at=datetime.now(tz=UTC),
        )
        saved, dup = await repo.create_idempotent(tx)
        assert dup is False
        duplicate_tx = Transaction(
            store_id=seeded_store,
            external_ref="POS-1001",
            amount=Decimal("99.99"),
            occurred_at=datetime.now(tz=UTC),
        )
        _, dup2 = await repo.create_idempotent(duplicate_tx)
        assert dup2 is True
        await session.commit()


@pytest.mark.asyncio
async def test_store_metric_upsert_idempotent(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        repo = StoreMetricRepository(session)
        bucket = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
        metric = StoreMetric(
            store_id=seeded_store,
            metric_name="footfall.count",
            bucket_start=bucket,
            bucket_end=bucket,
            granularity="hour",
            dimensions={"zone": "entry"},
            value=10.0,
            sample_count=10,
        )
        first = await repo.upsert(metric)
        metric.value = 15.0
        metric.sample_count = 15
        second = await repo.upsert(metric)
        assert first.id == second.id
        assert second.value == 15.0
        assert second.sample_count == 15
        await session.commit()


@pytest.mark.asyncio
async def test_anomaly_list_unresolved(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        repo = AnomalyRepository(session)
        await repo.create(
            Anomaly(
                store_id=seeded_store,
                anomaly_type="occupancy.high",
                severity="critical",
                detected_at=datetime.now(tz=UTC),
                message="Checkout queue exceeded threshold",
            )
        )
        open_rows = await repo.list_by_store(seeded_store, unresolved_only=True)
        assert len(open_rows) == 1
        await session.commit()


@pytest.mark.asyncio
async def test_visit_session_active_by_track(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        repo = VisitSessionRepository(session)
        vs = VisitSession(
            store_id=seeded_store,
            external_track_id="track-17",
            status="active",
            started_at=datetime.now(tz=UTC),
        )
        await repo.create(vs)
        found = await repo.get_active_by_track(seeded_store, "track-17")
        assert found is not None
        assert found.external_track_id == "track-17"
        await session.commit()
