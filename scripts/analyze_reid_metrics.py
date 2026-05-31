#!/usr/bin/env python3
"""Measure visitor Re-ID quality: ID switches, duplicate visitors, session matching."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cv2

from pipeline.config import PipelineConfig, resolve_video_path
from pipeline.detect import build_detectors_for_cameras
from pipeline.tracker import MultiCameraPipeline

# One synthetic visitor path across the store + one staff backroom track.
EXPECTED_VISITOR_GLOBAL_IDS = 1
EXPECTED_STAFF_GLOBAL_IDS = 1
EXPECTED_VISITOR_SESSIONS = 1


@dataclass
class ReIdMetrics:
    unique_global_ids: int = 0
    visitor_global_ids: int = 0
    staff_global_ids: int = 0
    local_track_fragments: int = 0
    global_id_switches: int = 0
    cross_camera_links: int = 0
    visitor_sessions: int = 0
    duplicate_session_ids: int = 0
    reentry_sessions: int = 0
    cameras_per_top_visitor: int = 0
    details: dict[str, int | float] = field(default_factory=dict)


def _apply_legacy_tuning(cfg: PipelineConfig) -> None:
    cfg.reid.update(
        {
            "cosine_threshold": 0.65,
            "match_score_threshold": 0.72,
            "no_embedding_match_threshold": 0.72,
            "same_camera_recovery_enabled": False,
            "mock_shared_visitor_embedding": False,
            "embedding_ema_alpha": 1.0,
            "min_crop_height_px": 80,
            "handoff_seconds": {
                "entry_to_floor": 120,
                "floor_to_billing": 180,
                "billing_to_backroom": 300,
                "floor_to_floor": 240,
            },
        }
    )
    cfg.tracker.update(
        {
            "track_thresh": 0.35,
            "track_buffer": 30,
            "match_thresh": 0.80,
            "mock_track_thresh": 0.25,
            "mock_match_thresh": 0.55,
            "mock_track_buffer": 30,
        }
    )
    cfg.session.pop("merge_active_within_seconds", None)


def _run_pipeline(cfg: PipelineConfig, *, max_frames: int) -> tuple[MultiCameraPipeline, ReIdMetrics]:
    cfg.detector["mode"] = "mock"
    detectors = build_detectors_for_cameras(cfg.detector, cfg.cameras)
    multi = MultiCameraPipeline(cfg, detectors)

    global_by_camera: dict[str, set[str]] = defaultdict(set)
    staff_ids: set[str] = set()
    visitor_ids: set[str] = set()
    local_fragments = 0
    id_switches = 0
    last_global_by_cam: dict[str, str | None] = defaultdict(lambda: None)
    camera_sets_by_gid: dict[str, set[str]] = defaultdict(set)

    sample_fps = float(cfg.processing.get("sample_fps", 5.0))
    anchor = datetime.now(tz=UTC) - timedelta(minutes=10)

    for cam in cfg.cameras:
        video_path = resolve_video_path(str(cam.video))
        if not video_path.exists():
            continue
        cap = cv2.VideoCapture(str(video_path))
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(native_fps / max(sample_fps, 0.1))))
        pipeline = multi.pipeline_for(cam.id)
        sampled = 0
        frame_idx = 0
        while cap.isOpened() and (max_frames <= 0 or sampled < max_frames):
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % step != 0:
                frame_idx += 1
                continue
            ts = anchor + timedelta(seconds=sampled * (1.0 / max(sample_fps, 0.1)))
            result = pipeline.process_frame(
                frame, frame_index=frame_idx, frame_timestamp=ts
            )
            for track in result.tracks:
                gid = track.global_id
                global_by_camera[cam.id].add(gid)
                camera_sets_by_gid[gid].add(cam.id)
                if track.is_staff:
                    staff_ids.add(gid)
                else:
                    visitor_ids.add(gid)
                prev_gid = last_global_by_cam[cam.id]
                if prev_gid is not None and prev_gid != gid:
                    id_switches += 1
                last_global_by_cam[cam.id] = gid
            local_fragments += len(result.tracks)
            if result.ended_tracks:
                last_global_by_cam[cam.id] = None
            sampled += 1
            frame_idx += 1
        cap.release()

    sessions = multi.sessions.sessions
    visitor_sessions = [s for s in sessions if not s.metadata.get("staff")]
    session_by_gid: dict[str, list] = defaultdict(list)
    for session in visitor_sessions:
        session_by_gid[session.external_track_id].append(session)

    duplicate_sessions = sum(max(0, len(v) - 1) for v in session_by_gid.values())
    reentry_sessions = sum(1 for s in visitor_sessions if s.is_reentry)
    cross_camera_links = sum(1 for cams in camera_sets_by_gid.values() if len(cams) >= 2)

    top_visitor_cameras = 0
    if visitor_ids:
        top_gid = max(
            visitor_ids,
            key=lambda gid: len(camera_sets_by_gid.get(gid, set())),
        )
        top_visitor_cameras = len(camera_sets_by_gid.get(top_gid, set()))

    metrics = ReIdMetrics(
        unique_global_ids=len(visitor_ids | staff_ids),
        visitor_global_ids=len(visitor_ids),
        staff_global_ids=len(staff_ids),
        local_track_fragments=local_fragments,
        global_id_switches=id_switches,
        cross_camera_links=cross_camera_links,
        visitor_sessions=len(visitor_sessions),
        duplicate_session_ids=duplicate_sessions,
        reentry_sessions=reentry_sessions,
        cameras_per_top_visitor=top_visitor_cameras,
        details={
            "expected_visitor_global_ids": EXPECTED_VISITOR_GLOBAL_IDS,
            "expected_staff_global_ids": EXPECTED_STAFF_GLOBAL_IDS,
            "expected_visitor_sessions": EXPECTED_VISITOR_SESSIONS,
        },
    )
    return multi, metrics


def _score(metrics: ReIdMetrics) -> dict[str, float]:
    visitor_id_accuracy = max(
        0.0,
        1.0
        - abs(metrics.visitor_global_ids - EXPECTED_VISITOR_GLOBAL_IDS)
        / max(EXPECTED_VISITOR_GLOBAL_IDS, 1),
    )
    session_accuracy = max(
        0.0,
        1.0
        - abs(metrics.visitor_sessions - EXPECTED_VISITOR_SESSIONS)
        / max(EXPECTED_VISITOR_SESSIONS, 1),
    )
    switch_penalty = metrics.global_id_switches / max(metrics.local_track_fragments, 1)
    link_bonus = min(1.0, metrics.cameras_per_top_visitor / 4.0)
    overall = (
        0.35 * visitor_id_accuracy
        + 0.25 * session_accuracy
        + 0.20 * (1.0 - min(1.0, switch_penalty * 4))
        + 0.20 * link_bonus
    )
    return {
        "visitor_id_accuracy": round(visitor_id_accuracy, 4),
        "session_accuracy": round(session_accuracy, 4),
        "id_switch_rate": round(switch_penalty, 4),
        "cross_camera_link_score": round(link_bonus, 4),
        "overall_score": round(overall, 4),
    }


def run_analysis(*, legacy: bool = False, max_frames: int = 80) -> dict:
    cfg = PipelineConfig.load()
    if legacy:
        _apply_legacy_tuning(cfg)
    _, metrics = _run_pipeline(cfg, max_frames=max_frames)
    scores = _score(metrics)
    return {
        "mode": "legacy" if legacy else "improved",
        "max_frames_per_camera": max_frames,
        "metrics": metrics.__dict__,
        "scores": scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze visitor Re-ID metrics")
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-frames", type=int, default=80)
    args = parser.parse_args()

    result = run_analysis(legacy=args.legacy, max_frames=args.max_frames)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    m = result["metrics"]
    s = result["scores"]
    print(f"Mode: {result['mode']}")
    print(
        f"visitor_global_ids={m['visitor_global_ids']}  "
        f"visitor_sessions={m['visitor_sessions']}  "
        f"id_switches={m['global_id_switches']}  "
        f"cross_camera_links={m['cross_camera_links']}  "
        f"top_visitor_cameras={m['cameras_per_top_visitor']}"
    )
    print(
        f"overall_score={s['overall_score']:.1%}  "
        f"visitor_id_accuracy={s['visitor_id_accuracy']:.1%}  "
        f"id_switch_rate={s['id_switch_rate']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
