# Direct service tests to keep app/ coverage >= 96% for CI.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.funnel.pos_linker import (
    BillingTrackCandidate,
    PosLinkMode,
    PosTransactionCandidate,
    link_billing_to_pos,
)
from app.domain.reid.evidence import analyze_reid_evidence
from app.exceptions import NotFoundError
from app.models import Event
from app.repositories.anomaly_repository import AnomalyRepository
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.store_repository import StoreRepository
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.dashboard_service import DashboardService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService
from app.services.reid_evidence_service import ReIdEvidenceService
from tests.helpers.constants import DEMO_TENANT_ID


@pytest.mark.asyncio
async def test_dashboard_service_get_summary_direct(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        store_repo = StoreRepository(session)
        funnel = FunnelService(
            FunnelRepository(session), store_repo, EventRepository(session)
        )
        heatmap = HeatmapService(HeatmapRepository(session), store_repo)
        analytics = AnalyticsService(
            StoreMetricRepository(session),
            store_repo,
            EventRepository(session),
            AnomalyRepository(session),
        )
        anomalies = AnomalyService(
            HeatmapRepository(session),
            FunnelRepository(session),
            store_repo,
            AnomalyRepository(session),
            EventRepository(session),
        )
        dashboard = DashboardService(
            session, store_repo, funnel, heatmap, analytics, anomalies
        )

        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "entry_threshold",
                    "external_track_id": "dash-direct",
                    "class_label": "visitor",
                    "is_store_entry": True,
                },
                correlation_id="dash-direct",
                occurred_at=now - timedelta(minutes=10),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.frame.processed",
                schema_version="1.0.0",
                aggregate_type="pipeline_run",
                aggregate_id=uuid.uuid4(),
                payload={"frame_index": 1},
                correlation_id="frame-1",
                occurred_at=now - timedelta(minutes=1),
            )
        )
        await session.commit()

        summary = await dashboard.get_summary(seeded_store)
        keys = {k.key for k in summary.kpis}
        assert "unique_visitors" in keys
        assert "revenue" in keys
        assert summary.provenance.feed_status in {"fresh", "stale", "unknown"}
        assert DashboardService._feed_status(None) == "unknown"


def test_dashboard_weighted_avg_dwell() -> None:
    from unittest.mock import MagicMock

    zones = [
        MagicMock(avg_dwell_seconds=30.0, dwell_sample_count=2),
        MagicMock(avg_dwell_seconds=None, dwell_sample_count=0),
        MagicMock(avg_dwell_seconds=60.0, dwell_sample_count=1),
    ]
    assert DashboardService._weighted_avg_dwell(zones) == 40.0
    assert DashboardService._weighted_avg_dwell([]) is None


@pytest.mark.asyncio
async def test_funnel_retail_journeys_and_meta(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        svc = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        now = datetime.now(tz=UTC)
        track = f"{seeded_store}:journey-ci"
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "browse",
                    "external_track_id": track,
                    "camera_id": "00000000-0000-0000-0000-000000000201",
                    "class_label": "visitor",
                },
                correlation_id="j-ci-1",
                occurred_at=now - timedelta(minutes=20),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "billing_queue",
                    "external_track_id": track,
                    "camera_id": "00000000-0000-0000-0000-000000000205",
                    "class_label": "visitor",
                },
                correlation_id="j-ci-2",
                occurred_at=now - timedelta(minutes=10),
            )
        )
        from app.models import Transaction

        session.add(
            Transaction(
                store_id=seeded_store,
                external_ref="INV-CI",
                amount=Decimal("99.00"),
                occurred_at=now - timedelta(minutes=5),
                metadata_={
                    "external_track_id": track,
                    "order_id": "ci-001",
                    "journey_link": {"method": "sequential", "confidence": 0.75},
                },
            )
        )
        await session.commit()

        funnel = await svc.get_funnel(seeded_store)
        journeys = await svc.get_retail_journeys(seeded_store)
        assert funnel.meta.get("linked_purchases", 0) >= 1
        assert any(j.purchase is not None for j in journeys.journeys)


def test_reid_evidence_analyzer_cross_camera() -> None:
    now = datetime.now(tz=UTC)
    track = "store:track-x"

    class E:
        def __init__(self, cam: str, offset: int) -> None:
            self.payload = {
                "external_track_id": track,
                "camera_id": cam,
                "zone_type": "aisle",
            }
            self.occurred_at = now + timedelta(seconds=offset)

    analysis = analyze_reid_evidence(
        [E("cam-a", 0), E("cam-b", 30)],
        camera_names={"cam-a": "CAM A", "cam-b": "CAM B"},
        camera_graph=[{"from": "cam-a", "to": "cam-b", "priority": "P0"}],
    )
    assert analysis["cross_camera_count"] == 1
    assert analysis["cross_camera_tracks"][0].camera_count == 2


def test_pos_linker_time_window_mode() -> None:
    now = datetime(2026, 4, 10, 20, 0, tzinfo=UTC)
    billing = [BillingTrackCandidate("t1", now)]
    pos = [PosTransactionCandidate("tx1", "o1", "INV", now + timedelta(seconds=30), "10")]
    matches = link_billing_to_pos(
        billing, pos, mode=PosLinkMode.TIME_WINDOW, window_minutes=5
    )
    assert len(matches) == 1
    assert matches[0].link_method == "time_window"


@pytest.mark.asyncio
async def test_reid_evidence_service_not_found(db_session_factory) -> None:
    async with db_session_factory() as session:
        svc = ReIdEvidenceService(EventRepository(session), StoreRepository(session))
        with pytest.raises(NotFoundError):
            await svc.get_evidence(uuid.uuid4())


@pytest.mark.asyncio
async def test_heatmap_layout_and_dwell_paths(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        store_repo = StoreRepository(session)
        store = await store_repo.get_by_id(seeded_store)
        assert store is not None
        store.config = {
            "heatmap": {
                "use_layout": True,
                "layout_file": "app/domain/heatmap/brigade_road_layout.yaml",
            }
        }
        await session.flush()

        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.exited",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_id": "zone-1",
                    "zone_name": "Aisle",
                    "zone_type": "aisle",
                    "external_track_id": "hm-ci",
                    "class_label": "visitor",
                    "dwell_seconds": 12.5,
                },
                correlation_id="hm-exit",
                occurred_at=now,
            )
        )
        await session.commit()

        svc = HeatmapService(HeatmapRepository(session), store_repo)
        result = await svc.get_heatmap(seeded_store)
        assert result.meta["layout_mapped"] is True
        assert HeatmapService._extract_dwell_seconds({"dwell_seconds": 3}) == 3.0
        assert HeatmapService._overall_confidence([]) == "LOW"


@pytest.mark.asyncio
async def test_funnel_purchase_pos_orphan_key(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        from app.models import Transaction

        session.add(
            Transaction(
                store_id=seeded_store,
                external_ref="POS-ORPHAN",
                amount=Decimal("1.00"),
                occurred_at=datetime.now(tz=UTC),
                metadata_={"order_id": "orphan-99"},
            )
        )
        await session.commit()
        svc = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        result = await svc.get_funnel(seeded_store)
        purchase = next(s for s in result.stages if s.stage == "PURCHASE")
        assert purchase.count == 0
        journeys = await svc.get_retail_journeys(seeded_store, complete_only=True)
        assert journeys.meta.get("pos_orphan_purchases", 0) >= 1


@pytest.mark.asyncio
async def test_funnel_retail_journeys_store_not_found(db_session_factory) -> None:
    async with db_session_factory() as session:
        svc = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        with pytest.raises(NotFoundError):
            await svc.get_retail_journeys(uuid.uuid4())


@pytest.mark.asyncio
async def test_dashboard_store_not_found_and_stale_feed(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from unittest.mock import patch

    async with db_session_factory() as session:
        store_repo = StoreRepository(session)
        funnel = FunnelService(
            FunnelRepository(session), store_repo, EventRepository(session)
        )
        heatmap = HeatmapService(HeatmapRepository(session), store_repo)
        analytics = AnalyticsService(
            StoreMetricRepository(session),
            store_repo,
            EventRepository(session),
            AnomalyRepository(session),
        )
        anomalies = AnomalyService(
            HeatmapRepository(session),
            FunnelRepository(session),
            store_repo,
            AnomalyRepository(session),
            EventRepository(session),
        )
        dashboard = DashboardService(
            session, store_repo, funnel, heatmap, analytics, anomalies
        )
        with pytest.raises(NotFoundError):
            await dashboard.get_summary(uuid.uuid4())

        stale_at = datetime.now(tz=UTC) - timedelta(hours=48)
        with patch("app.services.dashboard_service.get_settings") as mock_settings:
            mock_settings.return_value.health_stale_feed_minutes = 30
            assert DashboardService._feed_status(stale_at) == "stale"
        assert DashboardService._stage(
            type("F", (), {"stages": []})(), "MISSING"
        ) is None


def test_heatmap_service_static_branches() -> None:
    from app.domain.heatmap.layout_mapping import load_store_layout

    layout = load_store_layout()
    assert HeatmapService._layout_section(layout, "type:aisle") is None
    assert HeatmapService._layout_section(layout, "layout:missing") is None
    section = HeatmapService._layout_section(layout, "layout:cash_counter")
    assert section is not None
    assert HeatmapService._extract_dwell_seconds({"dwell_ms": 5000}) == 5.0
    assert HeatmapService._extract_dwell_seconds({}) is None
    assert HeatmapService._resolve_zone({"zone_id": "z1", "zone_name": "A"})[0] == "id:z1"
    assert HeatmapService._resolve_zone({"zone_type": "Browse"})[0] == "type:browse"
    assert HeatmapService._resolve_zone({}) == (None, None, None)
    assert HeatmapService._overall_confidence([type("Z", (), {"data_confidence": "HIGH"})()]) == "HIGH"
    mixed = [
        type("Z", (), {"data_confidence": "HIGH"})(),
        type("Z", (), {"data_confidence": "LOW"})(),
    ]
    assert HeatmapService._overall_confidence(mixed) == "MEDIUM"


@pytest.mark.asyncio
async def test_heatmap_load_layout_branches(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        store_repo = StoreRepository(session)
        store = await store_repo.get_by_id(seeded_store)
        assert store is not None
        svc = HeatmapService(HeatmapRepository(session), store_repo)

        store.config = {"heatmap": {"use_layout": False}}
        assert svc._load_layout(store, seeded_store) is None

        store.config = {"heatmap": {"layout_file": "/nonexistent/layout.yaml"}}
        assert svc._load_layout(store, seeded_store) is None

        store.config = {
            "heatmap": {
                "use_layout": True,
                "layout_file": "app/domain/heatmap/brigade_road_layout.yaml",
            }
        }
        assert svc._load_layout(store, seeded_store) is not None


@pytest.mark.asyncio
async def test_heatmap_build_visits_skips_non_customer_and_no_dwell(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        svc = HeatmapService(HeatmapRepository(session), StoreRepository(session))
        now = datetime.now(tz=UTC)
        events = [
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "aisle", "class_label": "staff"},
                correlation_id="hm-staff",
                occurred_at=now,
            ),
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.exited",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "aisle", "class_label": "visitor"},
                correlation_id="hm-no-dwell",
                occurred_at=now,
            ),
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "aisle", "class_label": "visitor"},
                correlation_id="hm-enter",
                occurred_at=now,
            ),
        ]
        visits, camera_ids = svc._build_visits(events)
        assert len(visits) == 1
        assert visits[0].is_enter is True
        assert camera_ids == [None]


def test_pos_linker_auto_and_empty() -> None:
    now = datetime(2026, 4, 10, 20, 0, tzinfo=UTC)
    billing = [
        BillingTrackCandidate("t1", now),
        BillingTrackCandidate("t2", now + timedelta(minutes=10)),
    ]
    pos = [
        PosTransactionCandidate("tx1", "o1", "INV1", now + timedelta(hours=2), "10"),
        PosTransactionCandidate("tx2", "o2", "INV2", now + timedelta(hours=2, minutes=5), "20"),
    ]
    assert link_billing_to_pos([], pos) == []
    auto = link_billing_to_pos(billing, pos, mode=PosLinkMode.AUTO, window_minutes=5)
    assert len(auto) == 2
    assert {m.link_method for m in auto} == {"sequential"}


def test_reid_handoff_candidates() -> None:
    now = datetime.now(tz=UTC)
    cam_a = "00000000-0000-0000-0000-000000000201"
    cam_b = "00000000-0000-0000-0000-000000000205"

    class E:
        def __init__(self, track: str, cam: str, offset: int) -> None:
            self.payload = {
                "external_track_id": track,
                "camera_id": cam,
                "zone_type": "aisle",
            }
            self.occurred_at = now + timedelta(seconds=offset)

    analysis = analyze_reid_evidence(
        [
            E("track-a", cam_a, 0),
            E("track-a", cam_a, 10),
            E("track-b", cam_b, 40),
        ],
        camera_names={cam_a: "Entry", cam_b: "Billing"},
        camera_graph=[{"from": cam_a, "to": cam_b, "priority": "P0"}],
    )
    assert analysis["handoff_candidate_count"] >= 1
