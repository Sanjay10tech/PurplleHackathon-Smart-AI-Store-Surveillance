# PROMPT:
# Pipeline unit tests — mock detector, session manager, emitter JSONL, no GPU.
#
# CHANGES MADE:
# - Validates MockPersonDetector, session cooldown resume, GIR store prefix, and frame event emission.

"""Pipeline unit tests — mock detector, no GPU."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest

from pipeline.config import PipelineConfig
from pipeline.detect import MockPersonDetector, build_detector
from pipeline.emit import EventBuilder, EventEmitter
from pipeline.tracker import (
    GlobalIdentityRegistry,
    SessionManager,
    MultiCameraPipeline,
    point_in_polygon,
)


def test_point_in_polygon() -> None:
    square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert point_in_polygon(0.5, 0.5, square)
    assert not point_in_polygon(1.5, 0.5, square)


def test_mock_detector_returns_person() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    dets = MockPersonDetector().detect(frame)
    assert len(dets) == 1
    assert dets[0].confidence > 0.5


def test_session_reentry_within_cooldown() -> None:
    sm = SessionManager("store-1", {"reentry_cooldown_minutes": 30})
    t0 = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    s1, _ = sm.start_or_resume("track-a", at=t0, is_store_entry=True)
    sm.end("track-a", at=t0)
    s2, is_reentry = sm.start_or_resume("track-a", at=t0)
    assert not is_reentry
    assert s2.session_id == s1.session_id
    assert s2.status == "active"


def test_global_identity_registry_assigns_store_prefix() -> None:
    gir = GlobalIdentityRegistry(
        "00000000-0000-0000-0000-000000000101",
        reid_cfg={"enabled": True, "match_score_threshold": 0.99},
        camera_graph=[],
    )
    now = datetime.now(tz=UTC)
    gid = gir.resolve(
        camera_id="cam-a",
        local_track_id=1,
        embedding=None,
        now=now,
    )
    assert gid.startswith("00000000-0000-0000-0000-000000000101:")


def test_pipeline_mock_frame_produces_events() -> None:
    cfg = PipelineConfig.load()
    cfg.detector["mode"] = "mock"
    detector = build_detector(cfg.detector)
    multi = MultiCameraPipeline(cfg, detector)
    cam_id = cfg.cameras[0].id
    pipe = multi.pipeline_for(cam_id)

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    now = datetime.now(tz=UTC)
    result = pipe.process_frame(frame, frame_index=0, frame_timestamp=now)
    for i in range(1, 4):
        result = pipe.process_frame(
            frame,
            frame_index=i,
            frame_timestamp=now,
        )
    assert len(result.tracks) >= 1

    builder = EventBuilder(
        store_id=cfg.store_id,
        tenant_id=cfg.tenant_id,
        schema_version=cfg.schema_version,
        pipeline_run_id=uuid.uuid4(),
        correlation_id="test-corr",
    )
    event = builder.frame_processed(result, processing_ms=10)
    assert event["event_type"] == "vision.frame.processed"
    assert event["store_id"] == cfg.store_id
    assert "detections" in event["payload"]


def test_emitter_writes_jsonl(tmp_path) -> None:
    emitter = EventEmitter({"output_jsonl": str(tmp_path / "events.jsonl")}, store_id="s", tenant_id="t")
    emitter.add(
        {
            "event_type": "vision.zone.entered",
            "store_id": "s",
            "payload": {"zone_type": "browse"},
        }
    )
    out = emitter.write_jsonl()
    assert out.exists()
    assert "vision.zone.entered" in out.read_text(encoding="utf-8")
