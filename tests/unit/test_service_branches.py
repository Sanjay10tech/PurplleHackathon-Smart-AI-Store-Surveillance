# PROMPT:
# Service-layer branch coverage — funnel, heatmap, anomaly, analytics edge paths.
#
# CHANGES MADE:
# - Staff sessions, invalid payloads, empty datasets, merge/persisted anomalies, confidence tiers.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.funnel.stages import FunnelStageName, PURCHASE_EVENT_TYPE, ZONE_ENTER_EVENT_TYPE
from app.domain.heatmap.constants import ZONE_ENTER_EVENT_TYPE as HEAT_ENTER
from app.domain.heatmap.constants import ZONE_EXIT_EVENT_TYPE
from app.exceptions import NotFoundError
from app.models import Anomaly, Event, Store, Transaction, VisitSession
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.store_repository import StoreRepository
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService
from tests.helpers.constants import DEMO_TENANT_ID


@pytest.mark.asyncio
async def test_funnel_service_not_found(funnel_service) -> None:
    service, _ = funnel_service
    with pytest.raises(NotFoundError):
        await service.get_funnel(uuid.uuid4())


@pytest.mark.asyncio
async def test_funnel_service_staff_session_and_signal_edges(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        service = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        store = await StoreRepository(session).get_by_id(seeded_store)
        assert store is not None
        store.config = {
            "funnel": {
                "dedupe_by_track": False,
                "zone_type_mapping": {"custom_zone": "ZONE_VISIT", "bad_stage": "NOT_A_STAGE"},
            }
        }
        now = datetime.now(tz=UTC)
        staff_session = VisitSession(
            store_id=seeded_store,
            external_track_id="staff-track",
            status="completed",
            started_at=now - timedelta(hours=1),
            metadata_={"staff": True},
        )
        visitor = VisitSession(
            store_id=seeded_store,
            external_track_id="visitor-track",
            status="completed",
            started_at=now - timedelta(hours=1),
        )
        session.add(staff_session)
        session.add(visitor)
        await session.flush()

        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=staff_session.id,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse", "class_label": "visitor"},
                correlation_id="f-staff-session",
                occurred_at=now - timedelta(minutes=38),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=visitor.id,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "browse",
                    "class_label": "visitor",
                    "external_track_id": "visitor-track",
                },
                correlation_id="f1",
                occurred_at=now - timedelta(minutes=40),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=visitor.id,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"class_label": "staff", "zone_type": "browse"},
                correlation_id="f-staff",
                occurred_at=now - timedelta(minutes=35),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=visitor.id,
                event_type=PURCHASE_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="transaction",
                aggregate_id=uuid.uuid4(),
                payload={"funnel_stage": "PURCHASE", "external_track_id": "visitor-track"},
                correlation_id="f-purchase",
                occurred_at=now - timedelta(minutes=10),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=uuid.uuid4(),
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "unknown_zone"},
                correlation_id="f-unknown",
                occurred_at=now - timedelta(minutes=5),
            )
        )
        await session.commit()

        result = await service.get_funnel(seeded_store)
        assert result.unique_visitors == 1
        stages = {s.stage: s for s in result.stages}
        assert stages["ZONE_VISIT"].count == 1
        assert stages["PURCHASE"].count == 1


@pytest.mark.asyncio
async def test_funnel_service_resolve_helpers_directly(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        service = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        store = await StoreRepository(session).get_by_id(seeded_store)
        assert store is not None
        mapping = service._resolve_zone_mapping(store)
        assert service._resolve_stage_from_payload(
            {"funnel_stage": "INVALID"}, mapping
        ) is None
        assert service._resolve_stage_from_payload(
            {"funnel_stage": "ZONE_VISIT"}, mapping
        ) == FunnelStageName.ZONE_VISIT
        assert service._resolve_stage_from_payload(
            {"zone_type": "custom_missing"}, mapping
        ) is None


@pytest.mark.asyncio
async def test_heatmap_service_dwell_and_confidence_branches(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        service = HeatmapService(HeatmapRepository(session), StoreRepository(session))
        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=HEAT_ENTER,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_id": "z1", "zone_name": "A", "class_label": "visitor"},
                correlation_id="h1",
                occurred_at=now,
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=ZONE_EXIT_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_id": "z1", "dwell_ms": 5000, "class_label": "visitor"},
                correlation_id="h2",
                occurred_at=now + timedelta(minutes=1),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=ZONE_EXIT_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse", "dwell_seconds": 12, "class_label": "visitor"},
                correlation_id="h3",
                occurred_at=now + timedelta(minutes=2),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=HEAT_ENTER,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"class_label": "staff", "zone_type": "staff_only"},
                correlation_id="h-staff",
                occurred_at=now,
            )
        )
        await session.commit()

        result = await service.get_heatmap(seeded_store)
        assert result.meta["total_visits"] >= 1

        assert HeatmapService._resolve_zone({}) == (None, None, None)
        assert HeatmapService._resolve_zone({"zone_type": "browse"})[0] == "type:browse"
        assert HeatmapService._extract_dwell_seconds({}) is None
        assert HeatmapService._overall_confidence([]) == "LOW"
        assert HeatmapService._overall_confidence(
            [MagicMock(data_confidence="HIGH"), MagicMock(data_confidence="HIGH")]
        ) == "HIGH"


@pytest.mark.asyncio
async def test_anomaly_service_merge_persisted_and_custom_queue(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        store_repo = StoreRepository(session)
        store = await store_repo.get_by_id(seeded_store)
        assert store is not None
        store.config = {"anomalies": {"queue_zone_keys": ["type:custom_queue"]}}
        await session.flush()

        service = AnomalyService(
            HeatmapRepository(session),
            FunnelRepository(session),
            store_repo,
            __import__("app.repositories.anomaly_repository", fromlist=["AnomalyRepository"]).AnomalyRepository(session),
            EventRepository(session),
        )
        now = datetime.now(tz=UTC)
        session.add(
            Anomaly(
                store_id=seeded_store,
                anomaly_type="DEAD_ZONE",
                severity="info",
                detected_at=now,
                message="persisted only",
                context={"suggested_action": "Check layout"},
            )
        )
        await session.commit()

        result = await service.get_anomalies(seeded_store)
        assert any(item.source == "persisted" for item in result.items)
        assert AnomalyService._normalize_severity("unknown_level") == "UNKNOWN_LEVEL"
        assert AnomalyService._normalize_severity("warning") == "WARN"


@pytest.mark.asyncio
async def test_anomaly_service_not_found(anomaly_service) -> None:
    service, _ = anomaly_service
    with pytest.raises(NotFoundError):
        await service.get_anomalies(uuid.uuid4())


@pytest.mark.asyncio
async def test_analytics_service_store_not_found(analytics_service) -> None:
    service, _ = analytics_service
    with pytest.raises(NotFoundError):
        await service.get_metrics(uuid.uuid4())


@pytest.mark.asyncio
async def test_funnel_repository_empty_session_ids(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        repo = FunnelRepository(session)
        assert await repo.get_sessions_by_ids(seeded_store, []) == []
