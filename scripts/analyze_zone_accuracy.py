#!/usr/bin/env python3
"""Measure zone entry/exit accuracy against trajectory ground truth."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.config import PipelineConfig
from pipeline.tracker import TrackState, ZoneAnalyzer, ZoneTransition, bbox_foot_point


@dataclass(frozen=True)
class ExpectedTransition:
    zone_type: str
    event_type: str = "vision.zone.entered"
    direction: str | None = None


# Ground truth derived from mock trajectories in pipeline/config.yaml.
EXPECTED: dict[str, list[ExpectedTransition]] = {
    "00000000-0000-0000-0000-000000000201": [
        ExpectedTransition("aisle"),
        ExpectedTransition("promo_island"),
    ],
    "00000000-0000-0000-0000-000000000202": [
        ExpectedTransition("aisle"),
    ],
    "00000000-0000-0000-0000-000000000203": [
        ExpectedTransition("entry_threshold", direction="in"),
    ],
    "00000000-0000-0000-0000-000000000204": [
        ExpectedTransition("staff_only"),
    ],
    "00000000-0000-0000-0000-000000000205": [
        ExpectedTransition("billing_queue"),
    ],
}


def _foot_to_bbox(foot: tuple[float, float]) -> tuple[float, float, float, float]:
    fx, fy = foot
    return (fx - 0.04, fy - 0.22, 0.08, 0.22)


def simulate_camera(
    camera_id: str,
    foot_points: list[tuple[float, float]],
    zones: list[dict],
    zone_cfg: dict,
    *,
    frame_step_seconds: float = 0.2,
) -> list[ZoneTransition]:
    analyzer = ZoneAnalyzer(zones, "entry" if "203" in camera_id else "floor", zone_cfg)
    track = TrackState(
        local_track_id=1,
        global_id=f"sim:{camera_id}",
        camera_id=camera_id,
        bbox_xywh=_foot_to_bbox(foot_points[0]),
        confidence=0.9,
        foot_point=foot_points[0],
    )
    prev: dict[int, TrackState] = {}
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
    transitions: list[ZoneTransition] = []

    for foot in foot_points:
        track.bbox_xywh = _foot_to_bbox(foot)
        track.foot_point = foot
        for trans in analyzer.analyze(track, now=now, prev_tracks=prev):
            transitions.append(trans)
        prev = {1: _clone(track)}
        now += timedelta(seconds=frame_step_seconds)
    return transitions


def _clone(track: TrackState) -> TrackState:
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


def _match_key(trans: ZoneTransition) -> tuple[str, str, str | None]:
    return (trans.event_type, trans.zone_type, trans.direction)


def score_camera(
    observed: list[ZoneTransition],
    expected: list[ExpectedTransition],
) -> dict[str, float | int]:
    obs_keys = [_match_key(t) for t in observed if t.event_type == "vision.zone.entered"]
    exp_keys = [
        (e.event_type, e.zone_type, e.direction)
        for e in expected
    ]
    obs_counter = Counter(obs_keys)
    exp_counter = Counter(exp_keys)

    tp = sum(min(obs_counter[k], exp_counter[k]) for k in exp_counter)
    fp = sum(obs_counter.values()) - tp
    fn = sum(exp_counter.values()) - tp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "observed_enters": len(obs_keys),
        "expected_enters": len(exp_keys),
    }


def run_analysis(*, legacy: bool = False) -> dict:
    cfg = PipelineConfig.load()
    if legacy:
        zone_cfg = {
            "line_hysteresis": 0.0,
            "line_debounce_seconds": 0.0,
            "polygon_hysteresis": 0.0,
            "min_dwell_before_exit_ms": 0,
            "min_line_cross_displacement": 0.0,
            "same_type_debounce_seconds": 0.0,
            "dedupe_after_seconds": 0.0,
        }
    else:
        zone_cfg = cfg.zone_analysis
    trajectories = cfg.detector.get("mock_trajectories") or {}

    per_camera: dict[str, dict] = {}
    totals = Counter()

    for cam in cfg.cameras:
        points_raw = trajectories.get(cam.id)
        if not points_raw:
            continue
        foot_points = [(float(p[0]), float(p[1])) for p in points_raw]
        zones = cfg.zones_by_camera.get(cam.id, [])
        if legacy:
            zones = [
                {k: v for k, v in z.items() if k not in ("counting_only", "dedupe_after_zone_types", "dedupe_after_seconds")}
                for z in zones
            ]
        observed = simulate_camera(cam.id, foot_points, zones, zone_cfg)
        expected = EXPECTED.get(cam.id, [])
        metrics = score_camera(observed, expected)
        per_camera[cam.name] = {
            "metrics": metrics,
            "observed": [
                {
                    "event_type": t.event_type,
                    "zone_type": t.zone_type,
                    "direction": t.direction,
                    "dwell_ms": t.dwell_ms,
                }
                for t in observed
            ],
        }
        totals["tp"] += int(metrics["true_positives"])
        totals["fp"] += int(metrics["false_positives"])
        totals["fn"] += int(metrics["false_negatives"])
        totals["observed"] += int(metrics["observed_enters"])
        totals["expected"] += int(metrics["expected_enters"])

    tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    accuracy = tp / (tp + fp + fn) if (tp + fp + fn) else 1.0

    return {
        "mode": "legacy" if legacy else "improved",
        "aggregate": {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "accuracy": round(accuracy, 4),
            "observed_enters": totals["observed"],
            "expected_enters": totals["expected"],
        },
        "per_camera": per_camera,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze zone entry/exit accuracy")
    parser.add_argument("--legacy", action="store_true", help="Simulate pre-tuning logic")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    result = run_analysis(legacy=args.legacy)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        agg = result["aggregate"]
        print(f"Mode: {result['mode']}")
        print(
            f"Accuracy={agg['accuracy']:.1%}  Precision={agg['precision']:.1%}  "
            f"Recall={agg['recall']:.1%}  FP={agg['false_positives']}  FN={agg['false_negatives']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
