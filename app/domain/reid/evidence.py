"""Re-ID evidence analysis from ingested vision events."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrackCameraPresence:
    camera_id: str
    camera_name: str | None
    event_count: int
    first_seen: datetime
    last_seen: datetime
    zone_types: list[str] = field(default_factory=list)


@dataclass
class CrossCameraTrack:
    external_track_id: str
    track_suffix: str
    cameras: list[TrackCameraPresence]
    camera_count: int
    total_events: int
    journey_path: str


@dataclass
class HandoffCandidate:
    from_track_id: str
    to_track_id: str
    from_camera: str
    to_camera: str
    from_camera_name: str | None
    to_camera_name: str | None
    gap_seconds: float
    graph_priority: str
    reason: str


def analyze_reid_evidence(
    events: list,
    *,
    camera_names: dict[str, str],
    camera_graph: list[dict[str, str]],
    handoff_seconds: dict[str, float] | None = None,
) -> dict:
    """Build cross-camera Re-ID evidence from ingested events."""
    handoff_seconds = handoff_seconds or {
        "entry_to_floor": 150,
        "floor_to_billing": 210,
    }
    graph_edges = {(e["from"], e["to"]): e.get("priority", "P0") for e in camera_graph}

    by_track: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "count": 0,
        "first": None,
        "last": None,
        "zones": set(),
    }))

    for event in events:
        payload = event.payload or {}
        track_id = payload.get("external_track_id")
        camera_id = payload.get("camera_id")
        if not track_id or not camera_id:
            continue
        bucket = by_track[str(track_id)][str(camera_id)]
        bucket["count"] += 1
        ts = event.occurred_at
        bucket["first"] = ts if bucket["first"] is None or ts < bucket["first"] else bucket["first"]
        bucket["last"] = ts if bucket["last"] is None or ts > bucket["last"] else bucket["last"]
        zone_type = payload.get("zone_type")
        if zone_type:
            bucket["zones"].add(str(zone_type))

    cross_camera: list[CrossCameraTrack] = []
    single_camera = 0
    for track_id, cameras in by_track.items():
        if len(cameras) < 2:
            single_camera += 1
            continue
        presences = []
        total = 0
        for cam_id, data in sorted(cameras.items(), key=lambda x: x[1]["first"] or datetime.min):
            total += data["count"]
            presences.append(
                TrackCameraPresence(
                    camera_id=cam_id,
                    camera_name=camera_names.get(cam_id),
                    event_count=data["count"],
                    first_seen=data["first"],
                    last_seen=data["last"],
                    zone_types=sorted(data["zones"]),
                )
            )
        path = " → ".join(p.camera_name or p.camera_id[-4:] for p in presences)
        cross_camera.append(
            CrossCameraTrack(
                external_track_id=track_id,
                track_suffix=track_id.split(":")[-1][-12:],
                cameras=presences,
                camera_count=len(presences),
                total_events=total,
                journey_path=path,
            )
        )

    cross_camera.sort(key=lambda t: (-t.camera_count, -t.total_events))

    # Handoff candidates: different track IDs on linked cameras within window
    track_camera_times: dict[str, dict[str, tuple[datetime, datetime]]] = {}
    for track_id, cameras in by_track.items():
        track_camera_times[track_id] = {
            cam: (data["first"], data["last"])
            for cam, data in cameras.items()
            if data["first"] and data["last"]
        }

    candidates: list[HandoffCandidate] = []
    for (src, dst), priority in graph_edges.items():
        max_gap = handoff_seconds.get("entry_to_floor", 150)
        if priority == "P0":
            max_gap = handoff_seconds.get(
                "floor_to_billing" if "205" in dst else "entry_to_floor",
                max_gap,
            )
        for from_track, from_cams in track_camera_times.items():
            if src not in from_cams:
                continue
            from_end = from_cams[src][1]
            for to_track, to_cams in track_camera_times.items():
                if from_track == to_track or dst not in to_cams:
                    continue
                to_start = to_cams[dst][0]
                gap = (to_start - from_end).total_seconds()
                if 0 <= gap <= max_gap:
                    candidates.append(
                        HandoffCandidate(
                            from_track_id=from_track,
                            to_track_id=to_track,
                            from_camera=src,
                            to_camera=dst,
                            from_camera_name=camera_names.get(src),
                            to_camera_name=camera_names.get(dst),
                            gap_seconds=gap,
                            graph_priority=str(priority),
                            reason="temporal_handoff_unlinked_ids",
                        )
                    )

    candidates.sort(key=lambda c: c.gap_seconds)

    return {
        "unique_track_ids": len(by_track),
        "single_camera_tracks": single_camera,
        "cross_camera_tracks": cross_camera,
        "cross_camera_count": len(cross_camera),
        "handoff_candidates": candidates[:20],
        "handoff_candidate_count": len(candidates),
    }
