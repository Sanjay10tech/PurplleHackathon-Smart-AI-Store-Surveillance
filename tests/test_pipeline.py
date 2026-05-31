# PROMPT:
# Unit tests for the offline CCTV detection pipeline (geometry, sessions, Re-ID, events).
#
# CHANGES MADE:
# - Validates zone line crossing, session re-entry cooldown, cross-camera dedup, and EventBuilder schema.

"""Unit tests for the offline CCTV detection pipeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from pipeline.detect import MockPersonDetector, RawDetection, build_detector
from pipeline.emit import EventBuilder
from pipeline.tracker import (
    CrossCameraDedup,
    GlobalIdentityRegistry,
    SessionManager,
    StaffClassifier,
    TrackRecoveryRegistry,
    TrackState,
    ZoneAnalyzer,
    ZoneTransition,
    bbox_foot_point,
    cosine_similarity,
    line_side_value,
    point_in_polygon,
    scale_polygon,
    effective_line_side,
)


STORE_ID = "00000000-0000-0000-0000-000000000101"
TENANT_ID = "00000000-0000-0000-0000-000000000001"
CAM_ENTRY = "00000000-0000-0000-0000-000000000203"
CAM_FLOOR = "00000000-0000-0000-0000-000000000201"
CAM_BILLING = "00000000-0000-0000-0000-000000000205"


def _track(
    *,
    camera_id: str = CAM_ENTRY,
    foot: tuple[float, float] = (0.5, 0.5),
    global_id: str = "gid-1",
) -> TrackState:
    bbox = (foot[0] - 0.04, foot[1] - 0.2, 0.08, 0.22)
    return TrackState(
        local_track_id=1,
        global_id=global_id,
        camera_id=camera_id,
        bbox_xywh=bbox,
        confidence=0.9,
        foot_point=foot,
    )


class TestGeometry:
    def test_point_in_polygon(self) -> None:
        square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        assert point_in_polygon(0.5, 0.5, square)
        assert not point_in_polygon(1.5, 0.5, square)

    def test_line_side_crossing(self) -> None:
        p1, p2 = [0.0, 0.5], [1.0, 0.5]
        assert line_side_value(0.5, 0.3, p1, p2, [0, 1]) < 0
        assert line_side_value(0.5, 0.7, p1, p2, [0, 1]) > 0

    def test_effective_line_side_dead_zone(self) -> None:
        assert effective_line_side(0.004, 0.008) == 0.0
        assert effective_line_side(-0.02, 0.008) < 0

    def test_scale_polygon_shrinks(self) -> None:
        square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        inner = scale_polygon(square, 0.1, inward=True)
        assert point_in_polygon(0.5, 0.5, inner)
        assert not point_in_polygon(0.02, 0.5, inner)

    def test_bbox_foot_point(self) -> None:
        x, y = bbox_foot_point((0.1, 0.2, 0.3, 0.4))
        assert x == pytest.approx(0.25)
        assert y == pytest.approx(0.6)


class TestSessionManager:
    def test_entry_exit_and_reentry_after_cooldown(self) -> None:
        mgr = SessionManager(STORE_ID, {"reentry_cooldown_minutes": 30})
        t0 = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        gid = f"{STORE_ID}:visitor-1"

        session, reentry = mgr.start_or_resume(gid, at=t0, is_store_entry=True)
        assert reentry is False
        assert session.status == "active"

        ended = mgr.end(gid, at=t0 + timedelta(minutes=5))
        assert ended is not None
        assert ended.status == "completed"

        within, reentry2 = mgr.start_or_resume(gid, at=t0 + timedelta(minutes=10))
        assert reentry2 is False
        assert within.session_id == session.session_id
        assert within.status == "active"

        mgr.end(gid, at=t0 + timedelta(minutes=15))
        after, reentry3 = mgr.start_or_resume(gid, at=t0 + timedelta(minutes=50))
        assert reentry3 is True
        assert after.session_id != session.session_id

    def test_get_active_session(self) -> None:
        mgr = SessionManager(STORE_ID, {"reentry_cooldown_minutes": 30})
        t0 = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        gid = f"{STORE_ID}:visitor-1"
        session, _ = mgr.start_or_resume(gid, at=t0, is_store_entry=True)
        assert mgr.get_active(gid) == session
        mgr.end(gid, at=t0 + timedelta(minutes=1))
        assert mgr.get_active(gid) is None

    def test_attach_recovered_session_within_merge_window(self) -> None:
        mgr = SessionManager(
            STORE_ID,
            {"reentry_cooldown_minutes": 30, "merge_active_within_seconds": 60},
        )
        t0 = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        gid = f"{STORE_ID}:visitor-1"
        session, _ = mgr.start_or_resume(gid, at=t0, is_store_entry=True)
        mgr.end(gid, at=t0 + timedelta(seconds=10))
        attached = mgr.attach_recovered(gid, session_id=session.session_id, at=t0 + timedelta(seconds=20))
        assert attached == session.session_id
        assert mgr.get_active(gid) == session


class TestGlobalIdentityRegistry:
    def test_cross_camera_match(self) -> None:
        embedder_dim = 512
        vec = np.ones(embedder_dim, dtype=np.float32)
        vec /= np.linalg.norm(vec)
        gir = GlobalIdentityRegistry(
            STORE_ID,
            reid_cfg={
                "enabled": True,
                "cosine_threshold": 0.5,
                "match_score_threshold": 0.5,
                "registry_ttl_seconds": 3600,
                "handoff_seconds": {"entry_to_floor": 120},
                "weights": {"cosine": 0.55, "time_gap": 0.20, "camera_graph": 0.15},
            },
            camera_graph=[
                {"from": CAM_ENTRY, "to": CAM_FLOOR, "priority": "P0"},
            ],
            camera_roles={CAM_ENTRY: "entry", CAM_FLOOR: "floor"},
        )
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        gid1 = gir.resolve(
            camera_id=CAM_ENTRY,
            local_track_id=1,
            embedding=vec,
            now=now,
        )
        gid2 = gir.resolve(
            camera_id=CAM_FLOOR,
            local_track_id=9,
            embedding=vec,
            now=now + timedelta(seconds=30),
        )
        assert gid1 == gid2

    def test_same_camera_recovery_after_track_drop(self) -> None:
        vec = np.ones(512, dtype=np.float32)
        vec /= np.linalg.norm(vec)
        recovery = TrackRecoveryRegistry(
            {
                "same_camera_recovery_enabled": True,
                "same_camera_recovery_seconds": 20,
                "same_camera_recovery_threshold": 0.5,
            }
        )
        gir = GlobalIdentityRegistry(
            STORE_ID,
            reid_cfg={
                "enabled": True,
                "cosine_threshold": 0.5,
                "match_score_threshold": 0.99,
                "registry_ttl_seconds": 3600,
            },
            camera_graph=[],
            recovery=recovery,
        )
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        gid1 = gir.resolve(
            camera_id=CAM_ENTRY,
            local_track_id=1,
            embedding=vec,
            now=now,
            foot_point=(0.35, 0.25),
        )
        lost = TrackState(
            local_track_id=1,
            global_id=gid1,
            camera_id=CAM_ENTRY,
            bbox_xywh=(0.3, 0.2, 0.08, 0.22),
            confidence=0.9,
            foot_point=(0.35, 0.25),
            embedding=vec,
        )
        recovery.register_lost(lost, at=now + timedelta(seconds=1))
        gid2 = gir.resolve(
            camera_id=CAM_ENTRY,
            local_track_id=9,
            embedding=vec,
            now=now + timedelta(seconds=2),
            foot_point=(0.50, 0.54),
        )
        assert gid1 == gid2


class TestTrackRecoveryRegistry:
    def test_recovers_recent_same_camera_track(self) -> None:
        vec = np.ones(512, dtype=np.float32)
        vec /= np.linalg.norm(vec)
        recovery = TrackRecoveryRegistry({"same_camera_recovery_threshold": 0.5})
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        track = TrackState(
            local_track_id=1,
            global_id=f"{STORE_ID}:visitor-a",
            camera_id=CAM_ENTRY,
            bbox_xywh=(0.3, 0.2, 0.08, 0.22),
            confidence=0.9,
            foot_point=(0.35, 0.25),
            embedding=vec,
        )
        recovery.register_lost(track, at=now)
        recovered = recovery.try_recover(
            camera_id=CAM_ENTRY,
            embedding=vec,
            foot_point=(0.50, 0.54),
            now=now + timedelta(seconds=2),
        )
        assert recovered == track.global_id


class TestCrossCameraDedup:
    def test_suppresses_floor_aisle_when_billing_active(self) -> None:
        dedup = CrossCameraDedup(
            {
                "enabled": True,
                "rules": [
                    {
                        "suppress_camera": CAM_FLOOR,
                        "suppress_zone_types": ["aisle"],
                        "when_active": {
                            "camera": CAM_BILLING,
                            "zone_types": ["billing_queue"],
                        },
                        "within_seconds": 180,
                    }
                ],
            }
        )
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        billing_track = _track(camera_id=CAM_BILLING, global_id="gid-1")
        billing_trans = ZoneTransition(
            event_type="vision.zone.entered",
            zone_id="q1",
            zone_name="billing_queue",
            zone_type="billing_queue",
        )
        dedup.record(billing_track, billing_trans, now)

        floor_track = _track(camera_id=CAM_FLOOR, global_id="gid-1")
        floor_trans = ZoneTransition(
            event_type="vision.zone.entered",
            zone_id="a1",
            zone_name="aisle_circulation",
            zone_type="aisle",
        )
        assert dedup.should_suppress(floor_track, floor_trans, now + timedelta(seconds=10))


class TestZoneAnalyzer:
    @staticmethod
    def _prev(track: TrackState) -> TrackState:
        return TrackState(
            local_track_id=track.local_track_id,
            global_id=track.global_id,
            camera_id=track.camera_id,
            bbox_xywh=track.bbox_xywh,
            confidence=track.confidence,
            foot_point=track.foot_point,
            zones_inside=set(track.zones_inside),
            line_side=dict(track.line_side),
            line_side_sign=dict(track.line_side_sign),
            zone_entered_at=dict(track.zone_entered_at),
            last_line_cross_at=dict(track.last_line_cross_at),
            last_zone_enter_at=dict(track.last_zone_enter_at),
        )

    def test_entry_line_emits_direction(self) -> None:
        zones = [
            {
                "zone_id": "entry-line",
                "name": "entry_threshold",
                "zone_type": "entry_threshold",
                "kind": "line",
                "points": [[0.42, 0.33], [0.68, 0.48]],
                "direction_normal": [0.26, 0.15],
            }
        ]
        analyzer = ZoneAnalyzer(zones, "entry")
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        track = _track(foot=(0.35, 0.25))
        analyzer.analyze(track, now=now, prev_tracks={})
        prev1 = self._prev(track)
        track.foot_point = (0.55, 0.55)
        track.bbox_xywh = (0.51, 0.33, 0.08, 0.22)
        transitions = analyzer.analyze(
            track, now=now + timedelta(seconds=1), prev_tracks={1: prev1}
        )
        assert any(t.direction == "in" for t in transitions)

    def test_entrance_suppressed_after_entry_threshold(self) -> None:
        zones = [
            {
                "zone_id": "entry-line",
                "name": "entry_threshold",
                "zone_type": "entry_threshold",
                "kind": "line",
                "points": [[0.42, 0.33], [0.68, 0.48]],
                "direction_normal": [0.26, 0.15],
            },
            {
                "zone_id": "entry-landing",
                "name": "entry_landing",
                "zone_type": "entrance",
                "kind": "polygon",
                "dedupe_after_zone_types": ["entry_threshold"],
                "require_prior_zone_types": ["entry_threshold"],
                "points": [[0.05, 0.25], [0.55, 0.25], [0.55, 0.55], [0.05, 0.55]],
            },
        ]
        cfg = {"dedupe_after_seconds": 15.0}
        analyzer = ZoneAnalyzer(zones, "entry", cfg)
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        track = _track(foot=(0.35, 0.25))
        analyzer.analyze(track, now=now, prev_tracks={})
        prev1 = self._prev(track)
        track.foot_point = (0.55, 0.55)
        track.bbox_xywh = (0.51, 0.33, 0.08, 0.22)
        transitions = analyzer.analyze(
            track, now=now + timedelta(seconds=1), prev_tracks={1: prev1}
        )
        types = [
            t.zone_type
            for t in transitions
            if t.event_type == "vision.zone.entered"
        ]
        assert "entry_threshold" in types
        assert "entrance" not in types

    def test_polygon_exit_requires_min_dwell(self) -> None:
        zones = [
            {
                "zone_id": "z1",
                "name": "aisle",
                "zone_type": "aisle",
                "kind": "polygon",
                "points": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            }
        ]
        analyzer = ZoneAnalyzer(zones, "floor", {"min_dwell_before_exit_ms": 500})
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        track = _track(foot=(0.5, 0.5))
        prev_inside = TrackState(
            local_track_id=1,
            global_id=track.global_id,
            camera_id=track.camera_id,
            bbox_xywh=track.bbox_xywh,
            confidence=track.confidence,
            foot_point=track.foot_point,
            zones_inside=set(track.zones_inside),
            zone_entered_at=dict(track.zone_entered_at),
        )
        analyzer.analyze(track, now=now, prev_tracks={})
        track.foot_point = (1.5, 0.5)
        track.bbox_xywh = (1.46, -0.17, 0.08, 0.22)
        early = analyzer.analyze(
            track, now=now + timedelta(milliseconds=100), prev_tracks={1: prev_inside}
        )
        assert not early
        late = analyzer.analyze(
            track, now=now + timedelta(seconds=1), prev_tracks={1: track}
        )
        assert any(t.event_type == "vision.zone.exited" for t in late)


class TestEventBuilder:
    def test_zone_event_matches_ingest_schema(self) -> None:
        builder = EventBuilder(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
            schema_version="1.0.0",
            pipeline_run_id=uuid.uuid4(),
            correlation_id="test-corr",
        )
        track = _track()
        track.session_id = uuid.uuid4()
        transition = ZoneTransition(
            event_type="vision.zone.entered",
            zone_id="zone-cam3-entry-threshold",
            zone_name="entry_threshold",
            zone_type="entry_threshold",
            direction="in",
            is_reentry=False,
            is_store_exit=False,
        )
        event = builder.zone_event(track, transition, occurred_at=datetime.now(tz=UTC))
        assert event is not None
        assert event["event_type"] == "vision.zone.entered"
        assert event["schema_version"] == "1.0.0"
        assert event["store_id"] == STORE_ID
        assert event["payload"]["external_track_id"] == track.global_id
        assert event["payload"]["zone_type"] == "entry_threshold"
        assert event["payload"]["direction"] == "in"
        assert event["payload"]["is_store_entry"] is True
        assert "session_id" in event["payload"]


class TestDetector:
    def test_build_mock_detector(self) -> None:
        det = build_detector({"mode": "mock", "confidence": 0.9})
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        dets = det.detect(frame)
        assert len(dets) == 1
        assert isinstance(dets[0], RawDetection)

    def test_yolo_bbox_filters(self) -> None:
        from pipeline.detect import YoloV11PersonDetector

        det = object.__new__(YoloV11PersonDetector)
        det._confidence = 0.35
        det._min_bbox_h = 0.08
        det._min_bbox_area = 0.006
        det._max_bbox_area = 0.32
        det._min_aspect = 1.2
        det._max_aspect = 5.5
        assert det._passes_filters(0.08, 0.22, 0.75)
        assert not det._passes_filters(0.08, 0.04, 0.75)
        assert not det._passes_filters(0.45, 0.72, 0.75)


class TestStaffClassifier:
    STAFF_CFG = {
        "dark_pixel_ratio_threshold": 0.70,
        "dark_value_threshold": 80,
        "uniform_frames_required": 60,
        "uniform_frames_required_billing": 5,
        "billing_presence_seconds": 180,
        "billing_zone_dwell_seconds": 120,
        "consultation_dwell_seconds": 600,
        "long_presence_seconds": 900,
        "counter_dwell_seconds": 300,
        "shuttle_min_cycles": 3,
        "loiter_path_ratio": 4.0,
        "loiter_min_path_norm": 0.05,
    }

    def test_billing_uniform_faster_threshold(self) -> None:
        clf = StaffClassifier(self.STAFF_CFG, "billing")
        track = _track(camera_id=CAM_BILLING)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        for _ in range(5):
            clf.update_track(
                track,
                frame,
                now=now,
                staff_zone_ids=set(),
                zone_id_to_type={},
            )
        assert track.is_staff
        assert track.staff_reason == "dark_uniform"

    def test_billing_long_presence(self) -> None:
        clf = StaffClassifier(self.STAFF_CFG, "billing")
        track = _track(camera_id=CAM_BILLING)
        track.dark_uniform_frames = 0
        track.first_seen = datetime(2026, 4, 10, 19, 0, 0, tzinfo=UTC)
        frame = np.full((1080, 1920, 3), 200, dtype=np.uint8)
        now = track.first_seen + timedelta(seconds=181)
        clf.update_track(
            track,
            frame,
            now=now,
            staff_zone_ids=set(),
            zone_id_to_type={},
        )
        assert track.is_staff
        assert track.staff_reason == "billing_long_presence"

    def test_billing_zone_dwell(self) -> None:
        clf = StaffClassifier(self.STAFF_CFG, "billing")
        track = _track(camera_id=CAM_BILLING)
        track.dark_uniform_frames = 0
        track.first_seen = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        track.zones_inside.add("zone-cam5-billing")
        track.zone_entered_at["zone-cam5-billing"] = track.first_seen
        frame = np.full((1080, 1920, 3), 200, dtype=np.uint8)
        clf.update_track(
            track,
            frame,
            now=track.first_seen + timedelta(seconds=121),
            staff_zone_ids=set(),
            zone_id_to_type={"zone-cam5-billing": "billing_queue"},
        )
        assert track.is_staff
        assert track.staff_reason == "billing_zone_dwell"

    def test_repeated_shuttle(self) -> None:
        clf = StaffClassifier(self.STAFF_CFG, "floor")
        track = _track(camera_id=CAM_FLOOR)
        track.zone_type_visits = [
            "consultation",
            "aisle",
            "consultation",
            "aisle",
            "consultation",
            "aisle",
        ]
        frame = np.full((1080, 1920, 3), 200, dtype=np.uint8)
        clf.update_track(
            track,
            frame,
            now=datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC),
            staff_zone_ids=set(),
            zone_id_to_type={},
        )
        assert track.is_staff
        assert track.staff_reason == "repeated_shuttle"

    def test_repeated_movement_loiter(self) -> None:
        clf = StaffClassifier(self.STAFF_CFG, "floor")
        track = _track(camera_id=CAM_FLOOR, foot=(0.5, 0.5))
        track.foot_point_history = [(0.5 + 0.01 * (i % 2), 0.5) for i in range(40)]
        track.path_length = 0.2
        frame = np.full((1080, 1920, 3), 200, dtype=np.uint8)
        clf.update_track(
            track,
            frame,
            now=datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC),
            staff_zone_ids=set(),
            zone_id_to_type={},
        )
        assert track.is_staff
        assert track.staff_reason == "repeated_movement"

    def test_staff_zone_events_suppressed(self) -> None:
        builder = EventBuilder(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
            schema_version="1.0.0",
            pipeline_run_id=uuid.uuid4(),
            correlation_id="test-corr",
        )
        track = _track()
        track.is_staff = True
        track.class_label = "staff"
        transition = ZoneTransition(
            event_type="vision.zone.entered",
            zone_id="zone-cam5-billing",
            zone_name="billing_queue",
            zone_type="billing_queue",
        )
        assert builder.zone_event(track, transition, occurred_at=datetime.now(tz=UTC)) is None

    def test_mark_staff_ends_visitor_session(self) -> None:
        sessions = SessionManager(STORE_ID, {})
        at = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        session, _ = sessions.start_or_resume("gid-staff", at=at, is_store_entry=True)
        sessions.mark_staff("gid-staff", at=at + timedelta(minutes=5))
        assert session.metadata.get("staff") is True
        assert session.status == "completed"
        assert sessions.get_active("gid-staff") is None

    def test_gir_staff_not_merged_into_visitor(self) -> None:
        gir = GlobalIdentityRegistry(
            STORE_ID,
            reid_cfg={"enabled": True, "match_score_threshold": 0.5, "cosine_threshold": 0.3},
            camera_graph=[],
        )
        now = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
        emb = np.ones(512, dtype=np.float32)
        emb = emb / np.linalg.norm(emb)
        staff_gid = gir.resolve(
            camera_id=CAM_BILLING,
            local_track_id=1,
            embedding=emb,
            now=now,
            role_hint="staff",
        )
        visitor_gid = gir.resolve(
            camera_id=CAM_BILLING,
            local_track_id=2,
            embedding=emb,
            now=now + timedelta(seconds=5),
            role_hint="visitor",
        )
        assert staff_gid != visitor_gid
