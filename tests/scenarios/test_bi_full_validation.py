# PROMPT:
# Full BI validation — golden retail day, staff exclusion, idempotent ingest,
# empty/zero-purchase scenarios, and complete pipeline → analytics chain.
#
# CHANGES MADE:
# - Validates metrics, funnel, heatmap, anomalies, and health against pipeline-shaped data.
# - Asserts staff exclusion, re-entry dedupe, and duplicate ingest idempotency.

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient

from pipeline.config import PipelineConfig
from pipeline.detect import TrajectoryMockPersonDetector
from pipeline.emit import EventBuilder, EventEmitter
from pipeline.ingest import persist_sessions_to_db
from pipeline.run import process_synthetic_frames
from pipeline.tracker import MultiCameraPipeline
from tests.helpers.constants import DEMO_TENANT_ID
from tests.helpers.pipeline_event_seed import (
    RetailDayExpectations,
    _persist_event_dicts,
    build_staff_zone_event,
    build_visitor_journey_events,
    seed_pipeline_retail_day,
)
from tests.helpers.seed import seed_visit_session


@pytest.mark.asyncio
async def test_bi_golden_retail_day_all_endpoints(
    client: AsyncClient,
    db_session_factory,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    """Validate metrics, funnel, heatmap, anomalies, and health on realistic pipeline data."""
    async with db_session_factory() as session:
        expected = await seed_pipeline_retail_day(session, seeded_store, tenant_id=tenant_id)
        await session.commit()

    period_end = datetime.now(tz=UTC)
    period_start = period_end - timedelta(hours=24)
    params = {"from": period_start.isoformat(), "to": period_end.isoformat()}

    metrics = await client.get(f"/api/v1/stores/{seeded_store}/metrics", params=params)
    assert metrics.status_code == 200
    metrics_body = metrics.json()
    assert metrics_body["meta"]["source"] == "store_metrics"
    assert len(metrics_body["series"]) >= 1
    assert metrics_body["series"][0]["value"] == pytest.approx(expected.unique_visitors)

    funnel = await client.get(f"/api/v1/stores/{seeded_store}/funnel", params=params)
    assert funnel.status_code == 200
    funnel_body = funnel.json()
    stages = {s["stage"]: s for s in funnel_body["stages"]}
    assert funnel_body["unique_visitors"] >= expected.unique_visitors
    assert funnel_body["unique_visitors"] <= expected.unique_visitors + 1
    assert stages["ENTRY"]["count"] == expected.unique_visitors
    assert stages["PURCHASE"]["count"] == expected.purchase_count
    assert stages["BILLING_QUEUE"]["conversion_rate"] == pytest.approx(expected.conversion_rate)
    assert stages["ZONE_VISIT"]["re_entry_count"] >= 1

    heatmap = await client.get(f"/api/v1/stores/{seeded_store}/heatmap", params=params)
    assert heatmap.status_code == 200
    heatmap_body = heatmap.json()
    assert heatmap_body["meta"]["total_visits"] >= expected.unique_visitors
    queue_zones = [z for z in heatmap_body["zones"] if "billing" in z["zone_label"].lower()]
    assert sum(z["visit_count"] for z in queue_zones) >= expected.billing_queue_visits

    anomalies = await client.get(f"/api/v1/stores/{seeded_store}/anomalies", params=params)
    assert anomalies.status_code == 200
    anomaly_types = {item["anomaly_type"] for item in anomalies.json()["items"]}
    assert "QUEUE_SPIKE" in anomaly_types
    assert "STALE_FEED" not in anomaly_types
    spike = next(i for i in anomalies.json()["items"] if i["anomaly_type"] == "QUEUE_SPIKE")
    assert spike["context"]["spike_ratio"] >= expected.queue_spike_ratio_min

    health = await client.get("/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["checks"]["feed"] == "fresh"
    assert health_body["stale_feed"] is False


@pytest.mark.asyncio
async def test_staff_events_excluded_from_customer_metrics(
    funnel_service,
    heatmap_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    funnel, session = funnel_service
    heatmap, _ = heatmap_service

    visit = await seed_visit_session(
        session,
        seeded_store,
        tenant_id=tenant_id,
        track_id="visitor-only",
        zone_types=["browse"],
    )
    journey = build_visitor_journey_events(
        store_id=seeded_store,
        tenant_id=tenant_id,
        session_id=visit.id,
        external_track_id=visit.external_track_id or "visitor-only",
        started_at=visit.started_at,
    )
    staff = build_staff_zone_event(
        store_id=seeded_store,
        tenant_id=tenant_id,
        occurred_at=visit.started_at + timedelta(minutes=5),
    )
    await _persist_event_dicts(session, seeded_store, tenant_id, journey + [staff])
    await session.commit()

    funnel_result = await funnel.get_funnel(seeded_store)
    assert funnel_result.unique_visitors >= 1
    assert funnel_result.meta.get("session_count", funnel_result.unique_visitors) >= 1
    stages = {s.stage: s for s in funnel_result.stages}
    assert stages["ZONE_VISIT"].count == 1

    heatmap_result = await heatmap.get_heatmap(seeded_store)
    staff_zones = [z for z in heatmap_result.zones if "staff" in z.zone_label.lower()]
    assert staff_zones == []


@pytest.mark.asyncio
async def test_reentry_does_not_double_count_funnel_visitors(
    funnel_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = funnel_service
    visit = await seed_visit_session(
        session,
        seeded_store,
        tenant_id=tenant_id,
        track_id="reentry-visitor",
        with_reentry=True,
        with_purchase=True,
        zone_types=["browse", "checkout"],
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    assert result.unique_visitors == 1
    zone_stage = next(s for s in result.stages if s.stage == "ZONE_VISIT")
    assert zone_stage.count == 1
    assert zone_stage.re_entry_count == 1


@pytest.mark.asyncio
async def test_duplicate_batch_ingest_is_idempotent(
    client: AsyncClient,
    seeded_store: UUID,
    db_session_factory,
) -> None:
    async with db_session_factory() as session:
        visit = await seed_visit_session(session, seeded_store, tenant_id=DEMO_TENANT_ID)
        events = build_visitor_journey_events(
            store_id=seeded_store,
            tenant_id=DEMO_TENANT_ID,
            session_id=visit.id,
            external_track_id=visit.external_track_id or "dup-track",
            started_at=visit.started_at,
        )
        await session.commit()

    first = await client.post("/api/v1/events/ingest", json={"events": events})
    second = await client.post("/api/v1/events/ingest", json={"events": events})

    assert first.status_code == 202
    assert first.json()["summary"]["accepted"] == len(events)
    assert second.status_code == 202
    assert second.json()["summary"]["duplicate"] == len(events)
    assert second.json()["summary"]["accepted"] == 0


@pytest.mark.asyncio
async def test_empty_store_endpoints_stable(client: AsyncClient, seeded_store: UUID) -> None:
    metrics = await client.get(f"/api/v1/stores/{seeded_store}/metrics")
    funnel = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    heatmap = await client.get(f"/api/v1/stores/{seeded_store}/heatmap")
    anomalies = await client.get(f"/api/v1/stores/{seeded_store}/anomalies")

    assert metrics.json()["meta"]["source"] == "placeholder"
    assert funnel.json()["unique_visitors"] == 0
    assert heatmap.json()["zones"] == []
    assert any(i["anomaly_type"] == "STALE_FEED" for i in anomalies.json()["items"])


@pytest.mark.asyncio
async def test_zero_purchase_funnel_drop_off(
    client: AsyncClient,
    db_session_factory,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    async with db_session_factory() as session:
        visit = await seed_visit_session(
            session,
            seeded_store,
            tenant_id=tenant_id,
            track_id="no-purchase",
            with_purchase=False,
            zone_types=["browse", "checkout"],
        )
        await session.commit()

    response = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    stages = {s["stage"]: s for s in response.json()["stages"]}
    assert stages["BILLING_QUEUE"]["count"] == 1
    assert stages["PURCHASE"]["count"] == 0
    assert stages["BILLING_QUEUE"]["drop_off_rate"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_full_pipeline_to_anomalies_chain(
    client: AsyncClient,
    seeded_store: uuid.UUID,
    db_session_factory,
) -> None:
    """Video → Detection → Events → Ingest → Metrics → Funnel → Anomalies → Health."""
    cfg = PipelineConfig.load()
    entry_cam = next(c for c in cfg.cameras if c.role == "entry")
    detector = TrajectoryMockPersonDetector(
        [(0.35, 0.25), (0.42, 0.38), (0.50, 0.54), (0.52, 0.58)]
    )
    multi = MultiCameraPipeline(cfg, detector)
    run_id = uuid.uuid4()
    builder = EventBuilder(
        store_id=str(seeded_store),
        tenant_id=str(DEMO_TENANT_ID),
        schema_version="1.0.0",
        pipeline_run_id=run_id,
        correlation_id=f"bi-chain-{run_id.hex[:8]}",
    )
    emitter = EventEmitter({}, store_id=str(seeded_store), tenant_id=str(DEMO_TENANT_ID))

    anchor = datetime.now(tz=UTC) - timedelta(minutes=3)
    process_synthetic_frames(
        camera_id=entry_cam.id,
        pipeline=multi,
        builder=builder,
        emitter=emitter,
        frame_count=4,
        start_time=anchor,
        emit_every_n=1,
    )

    async with db_session_factory() as session:
        await persist_sessions_to_db(session, multi.sessions.sessions)
        await session.commit()

    ingest = await client.post("/api/v1/events/ingest", json={"events": emitter.events})
    assert ingest.status_code == 202

    metrics = await client.get(f"/api/v1/stores/{seeded_store}/metrics")
    funnel = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    heatmap = await client.get(f"/api/v1/stores/{seeded_store}/heatmap")
    anomalies = await client.get(f"/api/v1/stores/{seeded_store}/anomalies")
    health = await client.get("/health")

    meta = metrics.json()["meta"]
    msg = meta.get("message") or ""
    assert meta.get("source") in {"store_metrics", "events_sql"} or "vision events" in msg
    assert funnel.json()["unique_visitors"] >= 1
    assert len(heatmap.json()["zones"]) >= 1
    assert anomalies.status_code == 200
    assert health.json()["checks"]["feed"] == "fresh"


def test_validation_report_snapshot_matches_golden_day() -> None:
    """Documented expectations for docs/bi_validation_report.md."""
    expected = RetailDayExpectations(
        unique_visitors=10,
        purchase_count=3,
        conversion_rate=0.3,
        billing_queue_visits=38,
        queue_spike_ratio_min=1.5,
        staff_events_ingested=1,
    )
    report_path = __import__("pathlib").Path("docs/bi_validation_report.md")
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert str(expected.unique_visitors) in text
    assert "30%" in text or "0.3" in text
    assert "QUEUE_SPIKE" in text
