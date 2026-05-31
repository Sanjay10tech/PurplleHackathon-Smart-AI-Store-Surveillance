#!/usr/bin/env python3
"""Measure staff vs customer classification and customer-metric contamination."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from pipeline.tracker import StaffClassifier, TrackState

LEGACY_STAFF_CFG = {
    "dark_pixel_ratio_threshold": 0.70,
    "dark_value_threshold": 80,
    "uniform_frames_required": 60,
    "uniform_frames_required_billing": 60,
    "counter_dwell_seconds": 300,
    "billing_presence_seconds": 999_999,
    "long_presence_seconds": 999_999,
    "billing_zone_dwell_seconds": 999_999,
    "consultation_dwell_seconds": 999_999,
    "shuttle_min_cycles": 999,
    "loiter_path_ratio": 999.0,
    "loiter_min_path_norm": 999.0,
    "backroom_camera_roles": ["backroom"],
    "billing_camera_roles": [],
}

DEFAULT_STAFF_CFG = {
    "dark_pixel_ratio_threshold": 0.70,
    "dark_value_threshold": 80,
    "uniform_torso_fraction": 0.60,
    "uniform_frames_required": 60,
    "uniform_frames_required_billing": 30,
    "counter_dwell_seconds": 300,
    "billing_zone_dwell_seconds": 120,
    "consultation_dwell_seconds": 600,
    "billing_presence_seconds": 180,
    "long_presence_seconds": 900,
    "backroom_camera_roles": ["backroom"],
    "billing_camera_roles": ["billing"],
    "billing_zone_types": ["billing_queue", "checkout"],
    "consultation_zone_types": ["consultation"],
    "shuttle_min_cycles": 3,
    "shuttle_zone_pairs": [["consultation", "aisle"], ["billing_queue", "aisle"]],
    "movement_history_max": 120,
    "zone_visit_history_max": 24,
    "loiter_path_ratio": 4.0,
    "loiter_min_path_norm": 0.15,
}


@dataclass
class ScenarioResult:
    name: str
    legacy_staff: bool
    improved_staff: bool
    legacy_contaminates: bool
    improved_contaminates: bool


@dataclass
class StaffAnalysisReport:
    scenarios: list[ScenarioResult] = field(default_factory=list)
    legacy_contamination: int = 0
    improved_contamination: int = 0
    legacy_staff_detected: int = 0
    improved_staff_detected: int = 0

    @property
    def contamination_reduction_pct(self) -> float:
        if self.legacy_contamination == 0:
            return 0.0
        reduced = self.legacy_contamination - self.improved_contamination
        return round(100.0 * reduced / self.legacy_contamination, 1)


def _track(
    *,
    camera_role: str,
    foot: tuple[float, float] = (0.5, 0.5),
    dark_uniform: bool = False,
) -> tuple[TrackState, np.ndarray]:
    bbox = (foot[0] - 0.04, foot[1] - 0.2, 0.08, 0.22)
    track = TrackState(
        local_track_id=1,
        global_id="gid-test",
        camera_id="cam-test",
        bbox_xywh=bbox,
        confidence=0.9,
        foot_point=foot,
        first_seen=datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC),
    )
    if dark_uniform:
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    else:
        frame = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    return track, frame


def _legacy_classify(
    track: TrackState,
    frame: np.ndarray,
    *,
    camera_role: str,
    now: datetime,
    staff_zone_ids: set[str],
    zone_id_to_type: dict[str, str],
    frames: int = 1,
) -> bool:
    if camera_role == "backroom":
        track.is_staff = True
        track.class_label = "staff"
        return True
    clf = StaffClassifier(LEGACY_STAFF_CFG, camera_role)
    for _ in range(frames):
        x, y, w, h = track.bbox_xywh
        fh, fw = frame.shape[:2]
        x1, y1 = max(0, int(x * fw)), max(0, int(y * fh))
        x2, y2 = min(fw, int((x + w) * fw)), min(fh, int((y + h) * fh))
        crop = frame[y1:y2, x1:x2]
        if crop.size > 0:
            gray = crop.mean(axis=2) if crop.ndim == 3 else crop
            dark_ratio = float((gray < 80).mean())
            if dark_ratio >= 0.70:
                track.dark_uniform_frames += 1
            else:
                track.dark_uniform_frames = max(0, track.dark_uniform_frames - 1)
        if track.dark_uniform_frames >= 60:
            track.is_staff = True
            track.class_label = "staff"
        for zone_id in staff_zone_ids:
            if zone_id in track.zones_inside and zone_id in track.zone_entered_at:
                dwell = (now - track.zone_entered_at[zone_id]).total_seconds()
                if dwell >= 300:
                    track.is_staff = True
                    track.class_label = "staff"
    return track.is_staff


def _improved_classify(
    track: TrackState,
    frame: np.ndarray,
    *,
    camera_role: str,
    now: datetime,
    staff_zone_ids: set[str],
    zone_id_to_type: dict[str, str],
    frames: int = 1,
) -> bool:
    clf = StaffClassifier(DEFAULT_STAFF_CFG, camera_role)
    for _ in range(frames):
        clf.update_movement(track)
        clf.update_track(
            track,
            frame,
            now=now,
            staff_zone_ids=staff_zone_ids,
            zone_id_to_type=zone_id_to_type,
        )
    return track.is_staff


def run_analysis() -> StaffAnalysisReport:
    report = StaffAnalysisReport()
    base = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
    staff_zone = {"zone-cam5-staff"}
    zone_types = {"zone-cam5-staff": "staff_only", "zone-cam5-billing": "billing_queue"}

    scenarios: list[tuple[str, str, dict]] = [
        (
            "billing_counter_dark_uniform",
            "billing",
            {
                "dark_uniform": True,
                "frames": 30,
                "now": base + timedelta(seconds=30),
                "zones_inside": {"zone-cam5-billing"},
                "zone_entered_at": {"zone-cam5-billing": base},
            },
        ),
        (
            "billing_long_presence",
            "billing",
            {
                "dark_uniform": False,
                "frames": 1,
                "now": base + timedelta(seconds=200),
                "zones_inside": set(),
                "zone_entered_at": {},
            },
        ),
        (
            "consultation_shuttle",
            "floor",
            {
                "dark_uniform": False,
                "frames": 1,
                "now": base + timedelta(minutes=2),
                "zone_type_visits": [
                    "consultation",
                    "aisle",
                    "consultation",
                    "aisle",
                    "consultation",
                    "aisle",
                ],
            },
        ),
        (
            "counter_loiter",
            "floor",
            {
                "dark_uniform": False,
                "frames": 1,
                "now": base + timedelta(minutes=3),
                "foot_history": [(0.5 + 0.01 * (i % 2), 0.5) for i in range(40)],
                "path_length": 0.2,
            },
        ),
        (
            "brief_customer_visit",
            "floor",
            {
                "dark_uniform": False,
                "frames": 1,
                "now": base + timedelta(seconds=45),
            },
        ),
        (
            "staff_only_dwell",
            "floor",
            {
                "dark_uniform": False,
                "frames": 1,
                "now": base + timedelta(seconds=310),
                "zones_inside": staff_zone,
                "zone_entered_at": {"zone-cam5-staff": base},
            },
        ),
    ]

    for name, role, opts in scenarios:
        legacy_track, frame = _track(
            camera_role=role,
            dark_uniform=bool(opts.get("dark_uniform")),
        )
        improved_track, frame2 = _track(
            camera_role=role,
            dark_uniform=bool(opts.get("dark_uniform")),
        )
        now = opts.get("now", base)
        for track in (legacy_track, improved_track):
            track.zones_inside = set(opts.get("zones_inside", set()))
            track.zone_entered_at = dict(opts.get("zone_entered_at", {}))
            if "zone_type_visits" in opts:
                track.zone_type_visits = list(opts["zone_type_visits"])
            if "foot_history" in opts:
                track.foot_point_history = list(opts["foot_history"])
                track.path_length = float(opts.get("path_length", 0.0))

        legacy_staff = _legacy_classify(
            legacy_track,
            frame,
            camera_role=role,
            now=now,
            staff_zone_ids=staff_zone,
            zone_id_to_type=zone_types,
            frames=int(opts.get("frames", 1)),
        )
        improved_staff = _improved_classify(
            improved_track,
            frame2,
            camera_role=role,
            now=now,
            staff_zone_ids=staff_zone,
            zone_id_to_type=zone_types,
            frames=int(opts.get("frames", 1)),
        )

        legacy_contaminates = not legacy_staff and name != "brief_customer_visit"
        improved_contaminates = not improved_staff and name != "brief_customer_visit"

        result = ScenarioResult(
            name=name,
            legacy_staff=legacy_staff,
            improved_staff=improved_staff,
            legacy_contaminates=legacy_contaminates,
            improved_contaminates=improved_contaminates,
        )
        report.scenarios.append(result)
        if legacy_staff:
            report.legacy_staff_detected += 1
        if improved_staff:
            report.improved_staff_detected += 1
        if legacy_contaminates:
            report.legacy_contamination += 1
        if improved_contaminates:
            report.improved_contamination += 1

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze staff classification quality")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data" / "staff_classification_results.json",
    )
    args = parser.parse_args()

    report = run_analysis()
    payload = {
        "legacy_contamination": report.legacy_contamination,
        "improved_contamination": report.improved_contamination,
        "contamination_reduction_pct": report.contamination_reduction_pct,
        "legacy_staff_detected": report.legacy_staff_detected,
        "improved_staff_detected": report.improved_staff_detected,
        "scenarios": [
            {
                "name": s.name,
                "legacy_staff": s.legacy_staff,
                "improved_staff": s.improved_staff,
                "legacy_contaminates_customer_metrics": s.legacy_contaminates,
                "improved_contaminates_customer_metrics": s.improved_contaminates,
            }
            for s in report.scenarios
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("Staff classification analysis")
    print(f"  Legacy staff detected:    {report.legacy_staff_detected}/{len(report.scenarios)}")
    print(f"  Improved staff detected:  {report.improved_staff_detected}/{len(report.scenarios)}")
    print(f"  Legacy contamination:     {report.legacy_contamination}")
    print(f"  Improved contamination:   {report.improved_contamination}")
    print(f"  Contamination reduction:  {report.contamination_reduction_pct}%")
    print(f"  Wrote {args.output}")


if __name__ == "__main__":
    main()
