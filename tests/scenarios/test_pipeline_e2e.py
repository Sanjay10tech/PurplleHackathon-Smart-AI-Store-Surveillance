# PROMPT:
# End-to-end pipeline test — video frames → detection → events → ingest → metrics.
#
# CHANGES MADE:
# - Trajectory mock simulates store entry crossing on CAM 3.
# - Sessions persisted, events batch-ingested via POST /api/v1/events/ingest.
# - Asserts metrics, funnel, and heatmap reflect ingested vision events.

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from pipeline.config import PipelineConfig
from pipeline.detect import TrajectoryMockPersonDetector
from pipeline.emit import EventBuilder, EventEmitter
from pipeline.ingest import persist_sessions_to_db
from pipeline.run import process_synthetic_frames
from pipeline.tracker import MultiCameraPipeline
from tests.helpers.constants import DEMO_STORE_ID, DEMO_TENANT_ID


@pytest.mark.asyncio
async def test_pipeline_video_to_metrics_e2e(
    client: AsyncClient,
    seeded_store: uuid.UUID,
    db_session_factory,
) -> None:
    """Video → Detection → Events → Ingest → Metrics/Funnel/Heatmap."""
    cfg = PipelineConfig.load()
    entry_cam = next(c for c in cfg.cameras if c.role == "entry")

    foot_path = [
        (0.35, 0.25),
        (0.38, 0.30),
        (0.42, 0.38),
        (0.46, 0.46),
        (0.50, 0.54),
        (0.52, 0.58),
    ]
    detector = TrajectoryMockPersonDetector(foot_path)
    multi = MultiCameraPipeline(cfg, detector)

    run_id = uuid.uuid4()
    builder = EventBuilder(
        store_id=str(seeded_store),
        tenant_id=str(DEMO_TENANT_ID),
        schema_version="1.0.0",
        pipeline_run_id=run_id,
        correlation_id=f"e2e-{run_id.hex[:8]}",
    )
    emitter = EventEmitter(
        {"validate_before_post": True},
        store_id=str(seeded_store),
        tenant_id=str(DEMO_TENANT_ID),
    )

    anchor = datetime.now(tz=UTC) - timedelta(minutes=5)
    process_synthetic_frames(
        camera_id=entry_cam.id,
        pipeline=multi,
        builder=builder,
        emitter=emitter,
        frame_count=len(foot_path),
        start_time=anchor,
        emit_every_n=2,
    )

    events = emitter.events
    assert len(events) >= 2
    assert any(e["event_type"] == "vision.frame.processed" for e in events)
    zone_events = [e for e in events if e["event_type"].startswith("vision.zone.")]
    assert zone_events, "expected at least one zone transition from entry crossing"

    sessions = multi.sessions.sessions
    assert sessions, "entry crossing should open a visitor session"

    async with db_session_factory() as session:
        persisted = await persist_sessions_to_db(session, sessions)
        await session.commit()
    assert persisted == len(sessions)

    ingest_resp = await client.post("/api/v1/events/ingest", json={"events": events})
    assert ingest_resp.status_code == 202
    summary = ingest_resp.json()["summary"]
    assert summary["accepted"] == len(events)
    assert summary["rejected"] == 0

    metrics_resp = await client.get(f"/api/v1/stores/{seeded_store}/metrics")
    assert metrics_resp.status_code == 200
    metrics_body = metrics_resp.json()
    meta = metrics_body["meta"]
    assert meta["source"] in ("store_metrics", "placeholder", "events_sql")
    assert metrics_body.get("unique_visitors", 0) >= 1 or meta.get("partial")

    funnel_resp = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    assert funnel_resp.status_code == 200
    stages = {s["stage"]: s for s in funnel_resp.json()["stages"]}
    assert stages["ENTRY"]["count"] >= 1

    heatmap_resp = await client.get(f"/api/v1/stores/{seeded_store}/heatmap")
    assert heatmap_resp.status_code == 200
    assert len(heatmap_resp.json()["zones"]) >= 1


@pytest.mark.asyncio
async def test_pipeline_sample_events_validate_and_batch_ingest(
    client: AsyncClient,
    seeded_store: uuid.UUID,
) -> None:
    """Sample event files validate against ingest schema and batch POST succeeds."""
    paths = EventEmitter.write_sample_files()
    batch = json.loads(paths["batch_ingest.json"].read_text(encoding="utf-8"))
    for event in batch["events"]:
        event["store_id"] = str(seeded_store)
        event["tenant_id"] = str(DEMO_TENANT_ID)
        event["payload"]["store_id"] = str(seeded_store)

    resp = await client.post("/api/v1/events/ingest", json=batch)
    assert resp.status_code == 202
    assert resp.json()["summary"]["accepted"] == 3


@pytest.mark.asyncio
async def test_pipeline_ingest_client_batch_partition() -> None:
    from pipeline.ingest import partition_batches

    events = [{"event_type": "vision.frame.processed", "i": i} for i in range(5)]
    batches = partition_batches(events, batch_size=2)
    assert len(batches) == 3
    assert len(batches[0]) == 2
    assert len(batches[-1]) == 1
