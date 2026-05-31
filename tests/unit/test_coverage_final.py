# Final branch coverage — repositories, routers, services, anomaly detector edges.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from app.domain.anomaly.detector import (
    AnomalyDetector,
    AnomalyThresholds,
    ConversionSummary,
    ZoneVisitSummary,
)
from app.domain.anomaly.types import AnomalyType
from app.domain.funnel.stages import PURCHASE_EVENT_TYPE, ZONE_ENTER_EVENT_TYPE
from app.models import Anomaly, Event, StoreMetric, Transaction, VisitSession
from app.repositories.crud.base import CRUDRepository
from app.repositories.event_repository import EventRepository
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.visit_session_repository import VisitSessionRepository
from app.routers.events import _bind_ingest_observability, _resolve_http_status
from app.schemas.events import BatchIngestSummary, EventAggregate, EventBatchIngestRequest, EventIngestRequest, IngestOutcome
from app.services.anomaly_service import AnomalyService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService
from tests.helpers.constants import DEMO_TENANT_ID


@pytest.mark.asyncio
async def test_event_repository_integrity_error_duplicate_id(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    event_id = uuid.uuid4()
    async with db_session_factory() as session:
        repo = EventRepository(session)
        saved = Event(
            id=event_id,
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={},
            correlation_id="race-id",
            occurred_at=datetime.now(tz=UTC),
        )

        async def raise_integrity(_entity: Event) -> Event:
            raise IntegrityError("statement", {}, Exception())

        with patch.object(repo, "get_by_id", side_effect=[None, saved]):
            with patch.object(repo, "create", side_effect=raise_integrity):
                result, outcome = await repo.create_idempotent(saved)
        assert outcome == IngestOutcome.DUPLICATE_ID
        assert result.id == event_id


@pytest.mark.asyncio
async def test_event_repository_integrity_error_reraises(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    async with db_session_factory() as session:
        repo = EventRepository(session)
        event = Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={},
            correlation_id="orphan",
            occurred_at=datetime.now(tz=UTC),
        )

        async def raise_integrity(_entity: Event) -> Event:
            raise IntegrityError("statement", {}, Exception())

        with patch.object(repo, "create", side_effect=raise_integrity):
            with pytest.raises(IntegrityError):
                await repo.create_idempotent(event)


@pytest.mark.asyncio
async def test_event_repository_list_filters(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    async with db_session_factory() as session:
        repo = EventRepository(session)
        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=tenant_id,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse"},
                correlation_id="list-1",
                occurred_at=now - timedelta(minutes=30),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=tenant_id,
                event_type="vision.frame.processed",
                schema_version="1.0.0",
                aggregate_type="pipeline_run",
                aggregate_id=uuid.uuid4(),
                payload={},
                correlation_id="list-2",
                occurred_at=now - timedelta(minutes=10),
            )
        )
        await session.flush()
        rows = await repo.list_by_store(
            seeded_store,
            event_types=["vision.zone.entered"],
            from_ts=now - timedelta(hours=1),
            to_ts=now,
        )
        assert len(rows) == 1
        assert rows[0].event_type == "vision.zone.entered"
        await session.commit()


@pytest.mark.asyncio
async def test_store_metric_integrity_error_recovery(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = StoreMetricRepository(session)
        bucket = datetime(2026, 5, 30, 7, 0, tzinfo=UTC)
        existing = StoreMetric(
            store_id=seeded_store,
            metric_name="footfall.count",
            bucket_start=bucket,
            bucket_end=bucket + timedelta(hours=1),
            granularity="hour",
            dimensions={},
            value=1.0,
            sample_count=1,
        )
        await repo.create(existing)
        duplicate = StoreMetric(
            store_id=seeded_store,
            metric_name="footfall.count",
            bucket_start=bucket,
            bucket_end=bucket + timedelta(hours=1),
            granularity="hour",
            dimensions={},
            value=9.0,
            sample_count=9,
        )

        async def raise_integrity(_entity: StoreMetric) -> StoreMetric:
            raise IntegrityError("statement", {}, Exception())

        with patch.object(repo, "create", side_effect=raise_integrity):
            saved = await repo.upsert(duplicate)
        assert saved.value == 9.0
        assert saved.sample_count == 9
        await session.commit()


@pytest.mark.asyncio
async def test_transaction_integrity_error_external_ref(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = TransactionRepository(session)
        now = datetime.now(tz=UTC)
        existing = Transaction(
            store_id=seeded_store,
            external_ref="pos-123",
            amount=Decimal("5.00"),
            occurred_at=now,
        )
        await repo.create(existing)
        duplicate = Transaction(
            store_id=seeded_store,
            external_ref="pos-123",
            amount=Decimal("99.00"),
            occurred_at=now,
        )

        async def raise_integrity(_entity: Transaction) -> Transaction:
            raise IntegrityError("statement", {}, Exception())

        with patch.object(repo, "create", side_effect=raise_integrity):
            saved, is_dup = await repo.create_idempotent(duplicate)
        assert is_dup is True
        assert saved.external_ref == "pos-123"
        await session.commit()


@pytest.mark.asyncio
async def test_transaction_duplicate_external_ref_before_create(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = TransactionRepository(session)
        now = datetime.now(tz=UTC)
        first = Transaction(
            store_id=seeded_store,
            external_ref="pos-dup",
            amount=Decimal("1.00"),
            occurred_at=now,
        )
        await repo.create(first)
        second = Transaction(
            store_id=seeded_store,
            external_ref="pos-dup",
            amount=Decimal("2.00"),
            occurred_at=now,
        )
        saved, is_dup = await repo.create_idempotent(second)
        assert is_dup is True
        assert saved.id == first.id
        await session.commit()


@pytest.mark.asyncio
async def test_visit_session_list_to_ts_filter(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = VisitSessionRepository(session)
        now = datetime.now(tz=UTC)
        session.add(
            VisitSession(
                store_id=seeded_store,
                external_track_id="old",
                status="completed",
                started_at=now - timedelta(days=2),
            )
        )
        session.add(
            VisitSession(
                store_id=seeded_store,
                external_track_id="recent",
                status="completed",
                started_at=now - timedelta(hours=1),
            )
        )
        await session.flush()
        rows = await repo.list_by_store(
            seeded_store, from_ts=now - timedelta(days=1), to_ts=now
        )
        assert len(rows) == 1
        assert rows[0].external_track_id == "recent"
        await session.commit()


@pytest.mark.asyncio
async def test_crud_delete_by_id_success(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = VisitSessionRepository(session)
        vs = VisitSession(
            store_id=seeded_store,
            external_track_id="delete-me",
            status="completed",
            started_at=datetime.now(tz=UTC),
        )
        created = await repo.create(vs)
        assert await repo.delete_by_id(created.id) is True
        assert await repo.get_by_id(created.id) is None
        await session.commit()


@pytest.mark.asyncio
async def test_funnel_cross_boundary_session_fetch(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        from app.repositories.funnel_repository import FunnelRepository
        from app.repositories.store_repository import StoreRepository

        service = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        now = datetime.now(tz=UTC)
        old_session = VisitSession(
            store_id=seeded_store,
            external_track_id="cross-boundary",
            status="completed",
            started_at=now - timedelta(days=3),
        )
        session.add(old_session)
        await session.flush()
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=old_session.id,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse", "class_label": "visitor"},
                correlation_id="cross",
                occurred_at=now - timedelta(minutes=5),
            )
        )
        await session.commit()
        result = await service.get_funnel(seeded_store)
        stages = {s.stage: s for s in result.stages}
        assert stages["ZONE_VISIT"].count >= 1


@pytest.mark.asyncio
async def test_funnel_event_without_session_id(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        from app.repositories.funnel_repository import FunnelRepository
        from app.repositories.store_repository import StoreRepository

        service = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=None,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse", "class_label": "visitor"},
                correlation_id="no-session",
                occurred_at=now,
            )
        )
        await session.commit()
        mapping = service._resolve_zone_mapping(
            await StoreRepository(session).get_by_id(seeded_store)  # type: ignore[arg-type]
        )
        signal = service._event_to_signal(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=None,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse"},
                correlation_id="x",
                occurred_at=now,
            ),
            mapping,
            {},
            {},
            True,
        )
        assert signal is None


def test_router_http_status_resolution() -> None:
    assert _resolve_http_status(BatchIngestSummary(total=2, accepted=0, duplicate=0, rejected=2)) == 422
    assert _resolve_http_status(BatchIngestSummary(total=2, accepted=1, duplicate=0, rejected=1)) == 207
    assert _resolve_http_status(BatchIngestSummary(total=1, accepted=1, duplicate=0, rejected=0)) == 202


def test_bind_ingest_observability_empty_batch() -> None:
    from starlette.requests import Request

    scope = {"type": "http", "path": "/ingest", "headers": []}
    request = Request(scope)
    _bind_ingest_observability(request, store_id=None, event_count=0)
    assert request.state.event_count == 0
    assert not hasattr(request.state, "store_id") or getattr(request.state, "store_id", None) is None


@pytest.mark.asyncio
async def test_router_batch_partial_success_207(
    client: AsyncClient, seeded_store: uuid.UUID
) -> None:
    good = {
        "event_type": "vision.frame.processed",
        "occurred_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "store_id": str(seeded_store),
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {},
    }
    bad = {
        "event_type": "invalid.prefix",
        "occurred_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "store_id": str(seeded_store),
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {},
    }
    response = await client.post("/api/v1/events/ingest", json={"events": [good, bad]})
    assert response.status_code == 207



@pytest.mark.asyncio
async def test_health_endpoint_returns_503_when_db_down(client: AsyncClient) -> None:
    with patch(
        "app.services.health_service.check_database_connection",
        AsyncMock(return_value=False),
    ):
        response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_heatmap_service_store_not_found(db_session_factory) -> None:
    from app.exceptions import NotFoundError
    from app.repositories.heatmap_repository import HeatmapRepository
    from app.repositories.store_repository import StoreRepository

    async with db_session_factory() as session:
        service = HeatmapService(HeatmapRepository(session), StoreRepository(session))
        with pytest.raises(NotFoundError):
            await service.get_heatmap(uuid.uuid4())


def test_heatmap_exit_without_dwell_skipped() -> None:
    from app.domain.heatmap.constants import ZONE_EXIT_EVENT_TYPE

    service = HeatmapService(MagicMock(), MagicMock())
    visits, _camera_ids = service._build_visits(
        [
            Event(
                store_id=uuid.uuid4(),
                tenant_id=DEMO_TENANT_ID,
                event_type=ZONE_EXIT_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse", "class_label": "visitor"},
                correlation_id="exit-no-dwell",
                occurred_at=datetime.now(tz=UTC),
            )
        ]
    )
    assert visits == []


def test_heatmap_overall_confidence_medium_only() -> None:
    assert HeatmapService._overall_confidence([MagicMock(data_confidence="MEDIUM")]) == "MEDIUM"


@pytest.mark.asyncio
async def test_anomaly_zone_summaries_skip_non_customer_and_missing_zone(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from app.repositories.anomaly_repository import AnomalyRepository
    from app.repositories.event_repository import EventRepository
    from app.repositories.funnel_repository import FunnelRepository
    from app.repositories.heatmap_repository import HeatmapRepository
    from app.repositories.store_repository import StoreRepository

    async with db_session_factory() as session:
        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.frame.processed",
                schema_version="1.0.0",
                aggregate_type="pipeline_run",
                aggregate_id=uuid.uuid4(),
                payload={},
                correlation_id="non-enter",
                occurred_at=now,
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"class_label": "staff", "zone_type": "browse"},
                correlation_id="staff-zone",
                occurred_at=now,
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"class_label": "visitor"},
                correlation_id="no-zone",
                occurred_at=now,
            )
        )
        await session.commit()

        service = AnomalyService(
            HeatmapRepository(session),
            FunnelRepository(session),
            StoreRepository(session),
            AnomalyRepository(session),
            EventRepository(session),
        )
        summaries = await service._zone_summaries(
            seeded_store, now - timedelta(hours=1), now + timedelta(minutes=1)
        )
        assert summaries == []


@pytest.mark.asyncio
async def test_anomaly_merge_skips_computed_duplicate_type(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from app.domain.anomaly.types import AnomalySeverity
    from app.repositories.anomaly_repository import AnomalyRepository
    from app.repositories.event_repository import EventRepository
    from app.repositories.funnel_repository import FunnelRepository
    from app.repositories.heatmap_repository import HeatmapRepository
    from app.repositories.store_repository import StoreRepository

    async with db_session_factory() as session:
        service = AnomalyService(
            HeatmapRepository(session),
            FunnelRepository(session),
            StoreRepository(session),
            AnomalyRepository(session),
            EventRepository(session),
        )
        now = datetime.now(tz=UTC)
        computed = [
            __import__(
                "app.domain.anomaly.detector", fromlist=["DetectedAnomaly"]
            ).DetectedAnomaly(
                id=uuid.uuid4(),
                anomaly_type=AnomalyType.STALE_FEED,
                severity=AnomalySeverity.WARN,
                detected_at=now,
                message="computed stale",
                suggested_action="fix feed",
                context={},
            )
        ]
        persisted = [
            Anomaly(
                store_id=seeded_store,
                anomaly_type="STALE_FEED",
                severity="info",
                detected_at=now,
                message="persisted stale",
            )
        ]
        merged = service._merge_results(computed, persisted)
        assert len(merged) == 1
        assert merged[0].source == "computed"


class TestAnomalyDetectorEdgeBranches:
    def test_queue_spike_skips_low_baseline_and_no_growth(self) -> None:
        store_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
        period_end = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
        cfg = AnomalyThresholds(queue_spike_min_baseline_visits=10)
        low_baseline = AnomalyDetector._detect_queue_spikes(
            store_id,
            period_end,
            [ZoneVisitSummary("type:checkout", "checkout", 20)],
            [ZoneVisitSummary("type:checkout", "checkout", 2)],
            {"type:checkout"},
            cfg,
        )
        assert low_baseline == []
        no_growth = AnomalyDetector._detect_queue_spikes(
            store_id,
            period_end,
            [ZoneVisitSummary("type:checkout", "checkout", 8)],
            [ZoneVisitSummary("type:checkout", "checkout", 10)],
            {"type:checkout"},
            cfg,
        )
        assert no_growth == []

    def test_dead_zone_skips_when_peak_zero(self) -> None:
        store_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
        period_end = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
        zones = [
            ZoneVisitSummary("type:a", "a", 0),
            ZoneVisitSummary("type:b", "b", 0),
        ]
        results = AnomalyDetector._detect_dead_zones(
            store_id,
            period_end,
            zones,
            AnomalyThresholds(dead_zone_min_zones=2, dead_zone_min_store_visits=0),
        )
        assert results == []
