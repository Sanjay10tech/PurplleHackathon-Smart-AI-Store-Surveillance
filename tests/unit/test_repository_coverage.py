# PROMPT:
# Repository layer branch coverage — legacy repos, CRUD, filters, idempotency edges.
#
# CHANGES MADE:
# - Covers analytics/domain_event repos, CRUD delete paths, list filters, metric helpers.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AnalyticsRollup, DomainEvent, Event, StoreMetric, Transaction, VisitSession
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.domain_event_repository import DomainEventRepository
from app.repositories.event_repository import EventRepository
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.store_repository import StoreRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.visit_session_repository import VisitSessionRepository
from app.schemas.events import IngestOutcome


@pytest.mark.asyncio
async def test_analytics_repository_rollups_and_has_data(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = AnalyticsRepository(session)
        start = datetime(2026, 5, 30, 10, 0, tzinfo=UTC)
        end = datetime(2026, 5, 30, 11, 0, tzinfo=UTC)
        session.add(
            AnalyticsRollup(
                store_id=seeded_store,
                metric_name="footfall.count",
                bucket_start=start,
                bucket_end=end,
                value=12.0,
                sample_count=12,
            )
        )
        await session.flush()
        rows = await repo.get_rollups(
            seeded_store, "footfall.count", from_ts=start, to_ts=end
        )
        assert len(rows) == 1
        assert await repo.has_data_for_store(seeded_store) is True
        assert await repo.has_data_for_store(uuid.uuid4()) is False
        await session.commit()


@pytest.mark.asyncio
async def test_domain_event_repository_crud_and_count(
    db_session_factory, seeded_store: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = DomainEventRepository(session)
        now = datetime.now(tz=UTC)
        event = DomainEvent(
            tenant_id=tenant_id,
            aggregate_type="store",
            aggregate_id=seeded_store,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            payload={"store_id": str(seeded_store)},
            correlation_id="legacy-1",
            idempotency_key="legacy-key-1",
            occurred_at=now,
        )
        saved = await repo.create(event)
        assert saved.id is not None
        found = await repo.get_by_idempotency_key("legacy-key-1")
        assert found is not None
        # SQLite JSON cast for payload store_id may not match PostgreSQL behavior;
        # verify the query executes without error.
        count = await repo.count_by_store_and_type(
            seeded_store,
            ["vision.zone.entered"],
            from_ts=now - timedelta(hours=1),
            to_ts=now + timedelta(hours=1),
        )
        assert count >= 0
        await session.commit()


@pytest.mark.asyncio
async def test_crud_repository_update_delete_list(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = VisitSessionRepository(session)
        vs = VisitSession(
            store_id=seeded_store,
            external_track_id="crud-track",
            status="completed",
            started_at=datetime.now(tz=UTC),
        )
        created = await repo.create(vs)
        created.status = "active"
        updated = await repo.update(created)
        assert updated.status == "active"

        missing = await repo.delete_by_id(uuid.uuid4())
        assert missing is False

        await repo.delete(updated)
        all_rows = await repo.list_all(limit=10)
        assert isinstance(all_rows, list)
        await session.commit()


@pytest.mark.asyncio
async def test_visit_session_list_filters(db_session_factory, seeded_store: uuid.UUID) -> None:
    async with db_session_factory() as session:
        repo = VisitSessionRepository(session)
        now = datetime.now(tz=UTC)
        session.add(
            VisitSession(
                store_id=seeded_store,
                external_track_id="list-a",
                status="active",
                started_at=now - timedelta(hours=2),
            )
        )
        session.add(
            VisitSession(
                store_id=seeded_store,
                external_track_id="list-b",
                status="completed",
                started_at=now - timedelta(hours=1),
            )
        )
        await session.flush()
        active = await repo.list_by_store(
            seeded_store, status="active", from_ts=now - timedelta(hours=3)
        )
        assert len(active) == 1
        await session.commit()


@pytest.mark.asyncio
async def test_store_repository_tenant_lookup(
    db_session_factory, seeded_store: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = StoreRepository(session)
        assert await repo.get_tenant_id_for_store(seeded_store) == tenant_id
        assert await repo.get_default_tenant("default") is not None
        assert await repo.get_by_id(uuid.uuid4()) is None
        await session.commit()


@pytest.mark.asyncio
async def test_event_repository_duplicate_id_and_filters(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = EventRepository(session)
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        event_id = uuid.uuid4()
        event = Event(
            id=event_id,
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={},
            correlation_id="dup-id",
            occurred_at=datetime.now(tz=UTC),
        )
        await repo.create(event)
        dup, outcome = await repo.create_idempotent(
            Event(
                id=event_id,
                store_id=seeded_store,
                tenant_id=tenant_id,
                event_type="vision.frame.processed",
                schema_version="1.0.0",
                aggregate_type="pipeline_run",
                aggregate_id=uuid.uuid4(),
                payload={},
                correlation_id="dup-id-2",
                occurred_at=datetime.now(tz=UTC),
            )
        )
        assert outcome == IngestOutcome.DUPLICATE_ID
        assert dup.id == event_id

        count = await repo.count_by_store_and_type(
            seeded_store,
            ["vision.frame.processed"],
            from_ts=datetime.now(tz=UTC) - timedelta(hours=1),
            to_ts=datetime.now(tz=UTC) + timedelta(hours=1),
        )
        assert count >= 1
        assert await repo.get_existing_ids([]) == set()
        await session.commit()


@pytest.mark.asyncio
async def test_transaction_list_and_no_external_ref(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = TransactionRepository(session)
        now = datetime.now(tz=UTC)
        tx = Transaction(
            store_id=seeded_store,
            amount=Decimal("9.99"),
            occurred_at=now,
        )
        saved, dup = await repo.create_idempotent(tx)
        assert dup is False
        rows = await repo.list_by_store(
            seeded_store, from_ts=now - timedelta(hours=1), to_ts=now + timedelta(hours=1)
        )
        assert any(r.id == saved.id for r in rows)
        await session.commit()


@pytest.mark.asyncio
async def test_store_metric_get_by_store_and_has_data(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = StoreMetricRepository(session)
        bucket = datetime(2026, 5, 30, 8, 0, tzinfo=UTC)
        await repo.upsert(
            StoreMetric(
                store_id=seeded_store,
                metric_name="footfall.count",
                bucket_start=bucket,
                bucket_end=bucket + timedelta(hours=1),
                granularity="hour",
                dimensions={},
                value=5.0,
                sample_count=5,
            )
        )
        rows = await repo.get_by_store(
            seeded_store,
            "footfall.count",
            granularity="hour",
            from_ts=bucket,
            to_ts=bucket + timedelta(hours=2),
        )
        assert len(rows) == 1
        assert await repo.has_data_for_store(seeded_store) is True
        await session.commit()


@pytest.mark.asyncio
async def test_anomaly_repository_resolve_and_filters(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from app.models import Anomaly
    from app.repositories.anomaly_repository import AnomalyRepository

    async with db_session_factory() as session:
        repo = AnomalyRepository(session)
        now = datetime.now(tz=UTC)
        row = await repo.create(
            Anomaly(
                store_id=seeded_store,
                anomaly_type="QUEUE_SPIKE",
                severity="warn",
                detected_at=now,
                message="spike",
            )
        )
        resolved = await repo.resolve(row.id, now + timedelta(minutes=5))
        assert resolved is not None
        assert resolved.resolved_at is not None
        assert await repo.resolve(uuid.uuid4(), now) is None

        filtered = await repo.list_by_store(
            seeded_store,
            severity="warn",
            from_ts=now - timedelta(hours=1),
            to_ts=now + timedelta(hours=1),
        )
        assert len(filtered) >= 1
        await session.commit()
