"""ByteTrack tracking, zone analysis, sessions, staff classification, and cross-camera Re-ID."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from pipeline.detect import RawDetection


@dataclass
class TrackState:
    local_track_id: int
    global_id: str
    camera_id: str
    bbox_xywh: tuple[float, float, float, float]
    confidence: float
    foot_point: tuple[float, float]
    is_staff: bool = False
    class_label: str = "visitor"
    session_id: uuid.UUID | None = None
    zones_inside: set[str] = field(default_factory=set)
    line_side: dict[str, float] = field(default_factory=dict)
    line_side_sign: dict[str, int] = field(default_factory=dict)
    dark_uniform_frames: int = 0
    zone_entered_at: dict[str, datetime] = field(default_factory=dict)
    last_line_cross_at: dict[str, datetime] = field(default_factory=dict)
    last_zone_enter_at: dict[str, datetime] = field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    embedding: np.ndarray | None = None
    foot_point_history: list[tuple[float, float]] = field(default_factory=list)
    path_length: float = 0.0
    zone_type_visits: list[str] = field(default_factory=list)
    staff_reason: str | None = None


@dataclass
class ZoneTransition:
    event_type: str  # vision.zone.entered | vision.zone.exited
    zone_id: str
    zone_name: str
    zone_type: str
    direction: str | None = None
    dwell_ms: int | None = None
    is_reentry: bool = False
    is_store_exit: bool = False
    suppressed: bool = False


@dataclass
class SessionRecord:
    session_id: uuid.UUID
    store_id: str
    external_track_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str = "active"
    is_reentry: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FramePipelineResult:
    camera_id: str
    frame_index: int
    frame_timestamp: datetime
    tracks: list[TrackState]
    zone_transitions: list[tuple[TrackState, ZoneTransition]]
    ended_tracks: list[TrackState]


def bbox_foot_point(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = bbox
    return (x + w / 2, y + h)


def point_in_polygon(px: float, py: float, polygon: list[list[float]]) -> bool:
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > py) != (y2 > py)) and (px < (x2 - x1) * (py - y1) / (y2 - y1 + 1e-9) + x1):
            inside = not inside
    return inside


def line_side_value(
    px: float, py: float, p1: list[float], p2: list[float], normal: list[float] | None = None
) -> float:
    ax, ay = p1
    bx, by = p2
    vx, vy = bx - ax, by - ay
    if normal:
        nx, ny = normal
    else:
        nx, ny = -vy, vx
        norm = math.hypot(nx, ny) or 1.0
        nx, ny = nx / norm, ny / norm
    return (px - ax) * nx + (py - ay) * ny


def line_normal(
    p1: list[float], p2: list[float], normal: list[float] | None = None
) -> tuple[float, float]:
    ax, ay = p1
    bx, by = p2
    vx, vy = bx - ax, by - ay
    if normal:
        nx, ny = normal
    else:
        nx, ny = -vy, vx
    norm = math.hypot(nx, ny) or 1.0
    return nx / norm, ny / norm


def effective_line_side(side: float, hysteresis: float) -> float:
    """Collapse near-line jitter into a dead zone before sign comparison."""
    if abs(side) <= hysteresis:
        return 0.0
    return side


def line_side_sign(side: float, hysteresis: float) -> int:
    if side > hysteresis:
        return 1
    if side < -hysteresis:
        return -1
    return 0


def _polygon_centroid(polygon: list[list[float]]) -> tuple[float, float]:
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    return cx, cy


def scale_polygon(
    polygon: list[list[float]], margin: float, *, inward: bool = True
) -> list[list[float]]:
    """Shrink or expand polygon vertices relative to centroid (normalized coords)."""
    if margin <= 0:
        return polygon
    cx, cy = _polygon_centroid(polygon)
    factor = max(0.0, 1.0 - margin) if inward else 1.0 + margin
    return [[cx + (x - cx) * factor, cy + (y - cy) * factor] for x, y in polygon]


class AppearanceEmbedder:
    """Lightweight appearance vector for cross-camera matching."""

    def __init__(self, dim: int = 512) -> None:
        self._dim = dim

    def embed(self, frame_bgr: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
        import cv2

        h, w = frame_bgr.shape[:2]
        x, y, bw, bh = bbox
        x1 = max(0, int(x * w))
        y1 = max(0, int(y * h))
        x2 = min(w, int((x + bw) * w))
        y2 = min(h, int((y + bh) * h))
        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return np.zeros(self._dim, dtype=np.float32)

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist_h = np.histogram(hsv[:, :, 0], bins=16, range=(0, 180))[0].astype(np.float32)
        hist_s = np.histogram(hsv[:, :, 1], bins=16, range=(0, 256))[0].astype(np.float32)
        hist_v = np.histogram(hsv[:, :, 2], bins=16, range=(0, 256))[0].astype(np.float32)
        vec = np.concatenate([hist_h, hist_s, hist_v])
        if vec.sum() > 0:
            vec /= vec.sum()
        if vec.size < self._dim:
            vec = np.pad(vec, (0, self._dim - vec.size))
        else:
            vec = vec[: self._dim]
        norm = np.linalg.norm(vec) or 1.0
        return (vec / norm).astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / denom)


@dataclass
class _LostTrackSnapshot:
    global_id: str
    camera_id: str
    local_track_id: int
    embedding: np.ndarray | None
    foot_point: tuple[float, float]
    lost_at: datetime
    session_id: uuid.UUID | None


class TrackRecoveryRegistry:
    """Recover global IDs after ByteTrack local ID switches on the same camera."""

    def __init__(self, reid_cfg: dict[str, Any]) -> None:
        self._enabled = bool(reid_cfg.get("same_camera_recovery_enabled", True))
        self._ttl = timedelta(seconds=float(reid_cfg.get("same_camera_recovery_seconds", 20)))
        self._foot_threshold = float(reid_cfg.get("same_camera_foot_threshold", 0.18))
        self._score_threshold = float(reid_cfg.get("same_camera_recovery_threshold", 0.52))
        self._lost: list[_LostTrackSnapshot] = []

    def register_lost(self, track: TrackState, *, at: datetime) -> None:
        if not self._enabled or track.is_staff:
            return
        self._lost.append(
            _LostTrackSnapshot(
                global_id=track.global_id,
                camera_id=track.camera_id,
                local_track_id=track.local_track_id,
                embedding=(
                    track.embedding.copy() if track.embedding is not None else None
                ),
                foot_point=track.foot_point,
                lost_at=at,
                session_id=track.session_id,
            )
        )
        self._purge(at)

    def try_recover(
        self,
        *,
        camera_id: str,
        embedding: np.ndarray | None,
        foot_point: tuple[float, float],
        now: datetime,
    ) -> str | None:
        if not self._enabled:
            return None
        self._purge(now)
        best: _LostTrackSnapshot | None = None
        best_score = 0.0
        for snap in self._lost:
            if snap.camera_id != camera_id:
                continue
            foot_dist = math.hypot(
                foot_point[0] - snap.foot_point[0],
                foot_point[1] - snap.foot_point[1],
            )
            foot_score = max(0.0, 1.0 - foot_dist / max(self._foot_threshold, 1e-6))
            cosine = 0.45
            if embedding is not None and snap.embedding is not None:
                cosine = max(0.0, cosine_similarity(embedding, snap.embedding))
            score = 0.35 * foot_score + 0.65 * cosine
            if score > best_score:
                best_score = score
                best = snap
        if best is None or best_score < self._score_threshold:
            return None
        self._lost = [s for s in self._lost if s.global_id != best.global_id]
        return best.global_id

    def _purge(self, now: datetime) -> None:
        self._lost = [s for s in self._lost if now - s.lost_at <= self._ttl]


class GlobalIdentityRegistry:
    """Cross-camera deduplication via appearance + temporal + graph scoring."""

    def __init__(
        self,
        store_id: str,
        *,
        reid_cfg: dict[str, Any],
        camera_graph: list[dict[str, Any]],
        camera_roles: dict[str, str] | None = None,
        recovery: TrackRecoveryRegistry | None = None,
    ) -> None:
        self._store_id = store_id
        self._cfg = reid_cfg
        self._roles = camera_roles or {}
        self._recovery = recovery
        self._records: dict[str, dict[str, Any]] = {}
        self._ttl = timedelta(seconds=int(reid_cfg.get("registry_ttl_seconds", 2700)))
        self._match_threshold = float(reid_cfg.get("match_score_threshold", 0.72))
        self._no_embed_threshold = float(reid_cfg.get("no_embedding_match_threshold", 0.58))
        self._cosine_threshold = float(reid_cfg.get("cosine_threshold", 0.65))
        self._same_cam_cosine = float(reid_cfg.get("same_camera_cosine_threshold", 0.40))
        self._ema_alpha = float(reid_cfg.get("embedding_ema_alpha", 0.35))
        self._weights = reid_cfg.get("weights", {})
        self._handoff = reid_cfg.get("handoff_seconds", {})
        self._edges: dict[tuple[str, str], str] = {}
        for edge in camera_graph:
            self._edges[(edge["from"], edge["to"])] = str(edge.get("priority", "P0"))

    def _purge(self, now: datetime) -> None:
        expired = [
            gid for gid, rec in self._records.items() if now - rec["last_seen_at"] > self._ttl
        ]
        for gid in expired:
            del self._records[gid]

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        return cosine_similarity(a, b)

    def _max_handoff(self, from_cam: str, to_cam: str) -> float:
        pri = self._edges.get((from_cam, to_cam))
        from_role = self._roles.get(from_cam, "")
        to_role = self._roles.get(to_cam, "")
        if pri == "P0":
            if from_role == "entry":
                return float(self._handoff.get("entry_to_floor", 120))
            if to_role == "billing":
                return float(self._handoff.get("floor_to_billing", 180))
            return float(self._handoff.get("entry_to_floor", 120))
        if pri == "P1":
            return float(self._handoff.get("billing_to_backroom", 300))
        return float(self._handoff.get("floor_to_floor", 240))

    @staticmethod
    def _color_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
        return float(max(0.0, np.dot(a, b) / denom))

    def _update_embedding(self, rec: dict[str, Any], embedding: np.ndarray) -> None:
        prior = rec.get("embedding")
        if prior is None:
            rec["embedding"] = embedding
        else:
            blended = (1.0 - self._ema_alpha) * prior + self._ema_alpha * embedding
            norm = np.linalg.norm(blended) or 1.0
            rec["embedding"] = (blended / norm).astype(np.float32)
        rec["apparel_color"] = rec["embedding"][:48]

    def _touch(
        self,
        gid: str,
        *,
        camera_id: str,
        local_track_id: int,
        now: datetime,
        embedding: np.ndarray | None,
    ) -> str:
        rec = self._records[gid]
        rec["last_seen_at"] = now
        rec["last_camera_id"] = camera_id
        rec.setdefault("local_tracks", {})[camera_id] = local_track_id
        if embedding is not None:
            self._update_embedding(rec, embedding)
        return f"{self._store_id}:{gid}"

    def _try_p0_solo_handoff(self, camera_id: str, now: datetime) -> str | None:
        """
        Basic cross-camera link: when exactly one visitor was active on a P0
        source camera within the handoff window, continue that global ID.
        """
        source_cameras = [
            src for (src, dst) in self._edges if dst == camera_id and self._edges[(src, dst)] == "P0"
        ]
        for src_cam in source_cameras:
            max_gap = self._max_handoff(src_cam, camera_id)
            candidates: list[tuple[str, dict[str, Any]]] = []
            for gid, rec in self._records.items():
                if rec.get("role") == "staff":
                    continue
                if rec.get("last_camera_id") != src_cam:
                    continue
                gap = (now - rec["last_seen_at"]).total_seconds()
                if gap <= max_gap:
                    candidates.append((gid, rec))
            if len(candidates) == 1:
                return candidates[0][0]
        return None

    def resolve(
        self,
        *,
        camera_id: str,
        local_track_id: int,
        embedding: np.ndarray | None,
        now: datetime,
        role_hint: str = "visitor",
        foot_point: tuple[float, float] | None = None,
    ) -> str:
        if not self._cfg.get("enabled", True):
            return f"{self._store_id}:{camera_id}:{local_track_id}"

        self._purge(now)

        if (
            role_hint == "visitor"
            and self._recovery is not None
            and foot_point is not None
        ):
            recovered = self._recovery.try_recover(
                camera_id=camera_id,
                embedding=embedding,
                foot_point=foot_point,
                now=now,
            )
            if recovered is not None:
                gid = recovered.split(":", 1)[-1]
                if gid in self._records:
                    return self._touch(
                        gid,
                        camera_id=camera_id,
                        local_track_id=local_track_id,
                        now=now,
                        embedding=embedding,
                    )

        best_gid: str | None = None
        best_score = 0.0
        same_camera_best: str | None = None
        same_camera_score = 0.0

        for gid, rec in self._records.items():
            if rec.get("role") == "staff" and role_hint == "visitor":
                continue
            gap = (now - rec["last_seen_at"]).total_seconds()
            max_gap = self._max_handoff(rec["last_camera_id"], camera_id)
            if gap > max_gap:
                continue

            on_graph = (rec["last_camera_id"], camera_id) in self._edges
            same_camera = rec["last_camera_id"] == camera_id
            cosine = 0.0
            if embedding is not None and rec.get("embedding") is not None:
                cosine = self._cosine(embedding, rec["embedding"])
                min_cos = self._same_cam_cosine if same_camera else self._cosine_threshold
                if cosine < min_cos:
                    continue
            elif embedding is not None and rec.get("embedding") is None:
                continue

            time_score = max(0.0, 1.0 - gap / max(max_gap, 1.0))
            graph_score = 1.0 if on_graph else (0.45 if same_camera else 0.3)
            apparel_score = 0.0
            if embedding is not None and rec.get("apparel_color") is not None:
                apparel_score = self._color_similarity(embedding[:48], rec["apparel_color"])
            score = (
                float(self._weights.get("cosine", 0.55)) * max(0.0, cosine)
                + float(self._weights.get("time_gap", 0.20)) * time_score
                + float(self._weights.get("camera_graph", 0.15)) * graph_score
                + float(self._weights.get("apparel_color", 0.10)) * apparel_score
            )
            threshold = self._no_embed_threshold if embedding is None else self._match_threshold
            if same_camera and score > same_camera_score:
                same_camera_score = score
                same_camera_best = gid
            if score > best_score:
                best_score = score
                best_gid = gid

        pick_gid = best_gid
        pick_score = best_score
        pick_threshold = self._no_embed_threshold if embedding is None else self._match_threshold
        if same_camera_best is not None and same_camera_score >= pick_threshold * 0.9:
            pick_gid = same_camera_best
            pick_score = same_camera_score

        if pick_gid is not None and pick_score >= pick_threshold:
            return self._touch(
                pick_gid,
                camera_id=camera_id,
                local_track_id=local_track_id,
                now=now,
                embedding=embedding,
            )

        if self._cfg.get("p0_solo_handoff_enabled", True) and role_hint == "visitor":
            solo_gid = self._try_p0_solo_handoff(camera_id, now)
            if solo_gid is not None:
                return self._touch(
                    solo_gid,
                    camera_id=camera_id,
                    local_track_id=local_track_id,
                    now=now,
                    embedding=embedding,
                )

        new_gid = str(uuid.uuid4())
        self._records[new_gid] = {
            "embedding": embedding,
            "apparel_color": embedding[:48] if embedding is not None else None,
            "last_seen_at": now,
            "last_camera_id": camera_id,
            "role": role_hint,
            "local_tracks": {camera_id: local_track_id},
        }
        return f"{self._store_id}:{new_gid}"

    def mark_role(self, global_id: str, role: str) -> None:
        gid = global_id.split(":", 1)[-1]
        rec = self._records.get(gid)
        if rec is not None:
            rec["role"] = role


class SessionManager:
    """Visitor session lifecycle with re-entry cooldown."""

    def __init__(self, store_id: str, session_cfg: dict[str, Any]) -> None:
        self._store_id = store_id
        self._cooldown = timedelta(minutes=int(session_cfg.get("reentry_cooldown_minutes", 30)))
        self._merge_within = timedelta(
            seconds=int(session_cfg.get("merge_active_within_seconds", 45))
        )
        self._sessions: dict[uuid.UUID, SessionRecord] = {}
        self._active_by_global: dict[str, uuid.UUID] = {}
        self._history: dict[str, list[SessionRecord]] = {}
        self._last_seen_at: dict[str, datetime] = {}

    @property
    def sessions(self) -> list[SessionRecord]:
        return list(self._sessions.values())

    def get_active(self, global_id: str) -> SessionRecord | None:
        active_id = self._active_by_global.get(global_id)
        if active_id is None:
            return None
        session = self._sessions.get(active_id)
        if session is None or session.status != "active":
            return None
        return session

    def touch(self, global_id: str, *, at: datetime) -> None:
        self._last_seen_at[global_id] = at

    def attach_recovered(
        self,
        global_id: str,
        *,
        session_id: uuid.UUID | None,
        at: datetime,
    ) -> uuid.UUID | None:
        """Re-attach a session after same-camera track recovery."""
        active = self.get_active(global_id)
        if active is not None:
            self.touch(global_id, at=at)
            return active.session_id
        if session_id is not None and session_id in self._sessions:
            session = self._sessions[session_id]
            if session.status == "active":
                self._active_by_global[global_id] = session_id
                self.touch(global_id, at=at)
                return session_id
        last_at = self._last_seen_at.get(global_id)
        if last_at is not None and at - last_at <= self._merge_within:
            history = self._history.get(global_id, [])
            for session in reversed(history):
                if session.status == "active":
                    self._active_by_global[global_id] = session.session_id
                    self.touch(global_id, at=at)
                    return session.session_id
                if session.status == "completed" and session.ended_at:
                    if at - session.ended_at <= self._cooldown:
                        session.ended_at = None
                        session.status = "active"
                        self._active_by_global[global_id] = session.session_id
                        self.touch(global_id, at=at)
                        return session.session_id
        return None

    def start_or_resume(
        self,
        global_id: str,
        *,
        at: datetime,
        is_store_entry: bool = False,
    ) -> tuple[SessionRecord, bool]:
        active_id = self._active_by_global.get(global_id)
        if active_id and active_id in self._sessions:
            self.touch(global_id, at=at)
            return self._sessions[active_id], False

        prior = self._history.get(global_id, [])
        is_reentry = False
        if prior and prior[-1].ended_at:
            gap = at - prior[-1].ended_at
            if gap <= self._cooldown:
                session = prior[-1]
                session.ended_at = None
                session.status = "active"
                self._active_by_global[global_id] = session.session_id
                self.touch(global_id, at=at)
                return session, False
            is_reentry = True

        session = SessionRecord(
            session_id=uuid.uuid4(),
            store_id=self._store_id,
            external_track_id=global_id,
            started_at=at,
            is_reentry=is_reentry,
            metadata={"store_entry": is_store_entry},
        )
        self._sessions[session.session_id] = session
        self._active_by_global[global_id] = session.session_id
        self._history.setdefault(global_id, []).append(session)
        self.touch(global_id, at=at)
        return session, is_reentry

    def end(self, global_id: str, *, at: datetime) -> SessionRecord | None:
        active_id = self._active_by_global.pop(global_id, None)
        if active_id is None or active_id not in self._sessions:
            return None
        session = self._sessions[active_id]
        session.ended_at = at
        session.status = "completed"
        self.touch(global_id, at=at)
        return session

    def visitor_session_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.status in ("active", "completed"))

    def distinct_visitor_ids(self) -> set[str]:
        return {
            s.external_track_id
            for s in self._sessions.values()
            if not s.metadata.get("staff")
        }

    def mark_staff(self, global_id: str, *, at: datetime) -> None:
        active_id = self._active_by_global.pop(global_id, None)
        if active_id is None or active_id not in self._sessions:
            return
        session = self._sessions[active_id]
        session.metadata["staff"] = True
        session.ended_at = at
        session.status = "completed"
        self.touch(global_id, at=at)


class StaffClassifier:
    def __init__(self, staff_cfg: dict[str, Any], camera_role: str) -> None:
        self._dark_ratio = float(staff_cfg.get("dark_pixel_ratio_threshold", 0.70))
        self._dark_value = int(staff_cfg.get("dark_value_threshold", 80))
        self._frames_required = int(staff_cfg.get("uniform_frames_required", 60))
        self._frames_required_billing = int(
            staff_cfg.get("uniform_frames_required_billing", 30)
        )
        self._torso_fraction = float(staff_cfg.get("uniform_torso_fraction", 0.60))
        self._counter_dwell = int(staff_cfg.get("counter_dwell_seconds", 300))
        self._billing_zone_dwell = int(staff_cfg.get("billing_zone_dwell_seconds", 120))
        self._consultation_dwell = int(staff_cfg.get("consultation_dwell_seconds", 600))
        self._billing_presence = int(staff_cfg.get("billing_presence_seconds", 180))
        self._long_presence = int(staff_cfg.get("long_presence_seconds", 900))
        self._backroom_roles = set(staff_cfg.get("backroom_camera_roles", ["backroom"]))
        self._billing_roles = set(staff_cfg.get("billing_camera_roles", ["billing"]))
        self._billing_zone_types = set(
            staff_cfg.get("billing_zone_types", ["billing_queue", "checkout"])
        )
        self._consultation_zone_types = set(
            staff_cfg.get("consultation_zone_types", ["consultation"])
        )
        self._shuttle_min_cycles = int(staff_cfg.get("shuttle_min_cycles", 3))
        self._shuttle_zone_pairs = [
            frozenset(str(t) for t in pair)
            for pair in staff_cfg.get(
                "shuttle_zone_pairs",
                [["consultation", "aisle"], ["billing_queue", "aisle"]],
            )
        ]
        self._movement_history_max = int(staff_cfg.get("movement_history_max", 120))
        self._zone_visit_history_max = int(staff_cfg.get("zone_visit_history_max", 24))
        self._loiter_path_ratio = float(staff_cfg.get("loiter_path_ratio", 4.0))
        self._loiter_min_path = float(staff_cfg.get("loiter_min_path_norm", 0.15))
        self._camera_role = camera_role

    def is_backroom_camera(self) -> bool:
        return self._camera_role in self._backroom_roles

    def is_billing_camera(self) -> bool:
        return self._camera_role in self._billing_roles

    def update_movement(self, track: TrackState) -> None:
        if track.foot_point_history:
            prev = track.foot_point_history[-1]
            track.path_length += math.hypot(
                track.foot_point[0] - prev[0], track.foot_point[1] - prev[1]
            )
        track.foot_point_history.append(track.foot_point)
        if len(track.foot_point_history) > self._movement_history_max:
            track.foot_point_history.pop(0)

    def record_zone_enter(self, track: TrackState, zone_type: str) -> None:
        if track.zone_type_visits and track.zone_type_visits[-1] == zone_type:
            return
        track.zone_type_visits.append(zone_type)
        if len(track.zone_type_visits) > self._zone_visit_history_max:
            track.zone_type_visits.pop(0)

    def update_track(
        self,
        track: TrackState,
        frame_bgr: np.ndarray,
        *,
        now: datetime,
        staff_zone_ids: set[str],
        zone_id_to_type: dict[str, str],
    ) -> None:
        if track.is_staff:
            return

        if self.is_backroom_camera():
            self._mark_staff(track, "backroom_camera")
            return

        self._update_uniform(track, frame_bgr)
        frames_required = (
            self._frames_required_billing
            if self.is_billing_camera()
            else self._frames_required
        )
        if track.dark_uniform_frames >= frames_required:
            self._mark_staff(track, "dark_uniform")
            return

        if track.first_seen is not None:
            presence = (now - track.first_seen).total_seconds()
            if self.is_billing_camera() and presence >= self._billing_presence:
                self._mark_staff(track, "billing_long_presence")
                return
            if presence >= self._long_presence:
                self._mark_staff(track, "long_presence")
                return

        for zone_id in track.zones_inside:
            entered_at = track.zone_entered_at.get(zone_id)
            if entered_at is None:
                continue
            dwell = (now - entered_at).total_seconds()
            zone_type = zone_id_to_type.get(zone_id, "")
            if zone_id in staff_zone_ids and dwell >= self._counter_dwell:
                self._mark_staff(track, "staff_zone_dwell")
                return
            if zone_type in self._billing_zone_types and dwell >= self._billing_zone_dwell:
                self._mark_staff(track, "billing_zone_dwell")
                return
            if zone_type in self._consultation_zone_types and dwell >= self._consultation_dwell:
                self._mark_staff(track, "consultation_dwell")
                return

        if self._detect_shuttle(track):
            self._mark_staff(track, "repeated_shuttle")
            return

        if self._detect_loiter(track):
            self._mark_staff(track, "repeated_movement")
            return

    def _mark_staff(self, track: TrackState, reason: str) -> None:
        track.is_staff = True
        track.class_label = "staff"
        track.staff_reason = reason

    def _update_uniform(self, track: TrackState, frame_bgr: np.ndarray) -> None:
        x, y, w, h = track.bbox_xywh
        fh, fw = frame_bgr.shape[:2]
        x1, y1 = max(0, int(x * fw)), max(0, int(y * fh))
        x2, y2 = min(fw, int((x + w) * fw)), min(fh, int((y + h) * fh))
        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return
        torso_end = max(1, int(crop.shape[0] * self._torso_fraction))
        torso = crop[:torso_end]
        gray = torso.mean(axis=2) if torso.ndim == 3 else torso
        dark_ratio = float((gray < self._dark_value).mean())
        if dark_ratio >= self._dark_ratio:
            track.dark_uniform_frames += 1
        else:
            track.dark_uniform_frames = max(0, track.dark_uniform_frames - 1)

    def _detect_shuttle(self, track: TrackState) -> bool:
        visits = track.zone_type_visits
        min_len = self._shuttle_min_cycles * 2
        if len(visits) < min_len:
            return False
        for pair in self._shuttle_zone_pairs:
            cycles = 0
            for i in range(1, len(visits)):
                prev_type, curr_type = visits[i - 1], visits[i]
                if prev_type in pair and curr_type in pair and prev_type != curr_type:
                    cycles += 1
            if cycles >= self._shuttle_min_cycles:
                return True
        return False

    def _detect_loiter(self, track: TrackState) -> bool:
        if len(track.foot_point_history) < 30:
            return False
        if track.path_length < self._loiter_min_path:
            return False
        first = track.foot_point_history[0]
        last = track.foot_point_history[-1]
        net = math.hypot(last[0] - first[0], last[1] - first[1])
        return track.path_length / max(net, 0.005) >= self._loiter_path_ratio


@dataclass
class _ActiveZonePresence:
    camera_id: str
    zone_type: str
    since: datetime


class CrossCameraDedup:
    """Suppress duplicate zone events when the same visitor is active on overlapping cameras."""

    def __init__(self, dedup_cfg: dict[str, Any]) -> None:
        self._enabled = bool(dedup_cfg.get("enabled", True))
        self._rules = list(dedup_cfg.get("rules", []))
        self._window = timedelta(
            seconds=int(dedup_cfg.get("default_within_seconds", 180))
        )
        self._presence: dict[str, list[_ActiveZonePresence]] = {}

    def record(self, track: TrackState, transition: ZoneTransition, at: datetime) -> None:
        if not self._enabled:
            return
        gid = track.global_id
        entries = self._presence.setdefault(gid, [])
        if transition.event_type == "vision.zone.entered":
            entries.append(
                _ActiveZonePresence(
                    camera_id=track.camera_id,
                    zone_type=transition.zone_type,
                    since=at,
                )
            )
        elif transition.event_type == "vision.zone.exited":
            self._presence[gid] = [
                e
                for e in entries
                if not (e.camera_id == track.camera_id and e.zone_type == transition.zone_type)
            ]

    def should_suppress(
        self,
        track: TrackState,
        transition: ZoneTransition,
        at: datetime,
    ) -> bool:
        if not self._enabled or transition.event_type != "vision.zone.entered":
            return False
        for rule in self._rules:
            suppress_cam = str(rule.get("suppress_camera", ""))
            suppress_types = set(rule.get("suppress_zone_types", []))
            if track.camera_id != suppress_cam or transition.zone_type not in suppress_types:
                continue
            active = rule.get("when_active", {})
            active_cam = str(active.get("camera", ""))
            active_types = set(active.get("zone_types", []))
            within = timedelta(
                seconds=int(rule.get("within_seconds", self._window.total_seconds()))
            )
            for presence in self._presence.get(track.global_id, []):
                if presence.camera_id != active_cam or presence.zone_type not in active_types:
                    continue
                if at - presence.since <= within:
                    return True
        return False


class ByteTrackAdapter:
    """ByteTrack via supervision library."""

    def __init__(self, tracker_cfg: dict[str, Any]) -> None:
        import supervision as sv

        self._tracker = sv.ByteTrack(
            track_activation_threshold=float(tracker_cfg.get("track_thresh", 0.5)),
            lost_track_buffer=int(tracker_cfg.get("track_buffer", 30)),
            minimum_matching_threshold=float(tracker_cfg.get("match_thresh", 0.8)),
            frame_rate=int(tracker_cfg.get("frame_rate", 30)),
        )

    def update(
        self,
        frame_bgr: np.ndarray,
        detections: list[RawDetection],
    ) -> list[tuple[int, RawDetection]]:
        import supervision as sv

        h, w = frame_bgr.shape[:2]
        if not detections:
            tracked = self._tracker.update_with_detections(sv.Detections.empty())
            _ = tracked
            return []

        xyxy = []
        confs = []
        for det in detections:
            x, y, bw, bh = det.bbox_xywh
            xyxy.append([x * w, y * h, (x + bw) * w, (y + bh) * h])
            confs.append(det.confidence)

        dets = sv.Detections(
            xyxy=np.array(xyxy, dtype=np.float32),
            confidence=np.array(confs, dtype=np.float32),
            class_id=np.zeros(len(detections), dtype=int),
        )
        tracked = self._tracker.update_with_detections(dets)
        if tracked.tracker_id is None:
            return []

        results: list[tuple[int, RawDetection]] = []
        for i, tid in enumerate(tracked.tracker_id):
            if tid is None:
                continue
            x1, y1, x2, y2 = tracked.xyxy[i]
            bbox = (
                float(x1 / w),
                float(y1 / h),
                float((x2 - x1) / w),
                float((y2 - y1) / h),
            )
            conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.5
            results.append((int(tid), RawDetection(bbox_xywh=bbox, confidence=conf, class_id=0)))
        return results


class ZoneEventDebouncer:
    """Track-level debounce and line-crossing memory keyed by global_id."""

    def __init__(self, zone_cfg: dict[str, Any]) -> None:
        self._same_type = timedelta(seconds=float(zone_cfg.get("same_type_debounce_seconds", 3.0)))
        self._line_cross = timedelta(seconds=float(zone_cfg.get("line_debounce_seconds", 2.0)))
        self._last_enter: dict[str, dict[str, datetime]] = {}
        self._last_line_cross: dict[str, dict[str, datetime]] = {}

    def should_suppress_enter(self, global_id: str, zone_id: str, *, now: datetime) -> bool:
        last = self._last_enter.get(global_id, {}).get(zone_id)
        return last is not None and now - last <= self._same_type

    def should_suppress_line_cross(self, global_id: str, zone_id: str, *, now: datetime) -> bool:
        last = self._last_line_cross.get(global_id, {}).get(zone_id)
        return last is not None and now - last <= self._line_cross

    def record_enter(self, global_id: str, zone_id: str, *, now: datetime) -> None:
        self._last_enter.setdefault(global_id, {})[zone_id] = now

    def record_line_cross(self, global_id: str, zone_id: str, *, now: datetime) -> None:
        self._last_line_cross.setdefault(global_id, {})[zone_id] = now


class ZoneAnalyzer:
    def __init__(
        self,
        zones: list[dict[str, Any]],
        camera_role: str,
        zone_cfg: dict[str, Any] | None = None,
        zone_debouncer: ZoneEventDebouncer | None = None,
        line_state: dict[str, int] | None = None,
    ) -> None:
        self._zones = zones
        self._camera_role = camera_role
        self._debouncer = zone_debouncer
        self._line_state = line_state if line_state is not None else {}
        cfg = zone_cfg or {}
        self._line_hysteresis = float(cfg.get("line_hysteresis", 0.008))
        self._line_debounce = timedelta(seconds=float(cfg.get("line_debounce_seconds", 2.0)))
        self._polygon_hysteresis = float(cfg.get("polygon_hysteresis", 0.012))
        self._min_dwell_exit_ms = int(cfg.get("min_dwell_before_exit_ms", 500))
        self._min_line_displacement = float(cfg.get("min_line_cross_displacement", 0.015))
        self._same_type_debounce = timedelta(
            seconds=float(cfg.get("same_type_debounce_seconds", 3.0))
        )
        self._exclude_polygons = [
            z["points"]
            for z in zones
            if z.get("exclude_detections") and z.get("kind") == "polygon"
        ]
        self._staff_zone_ids = {z["zone_id"] for z in zones if z.get("zone_type") == "staff_only"}
        self._dedupe_after: dict[str, tuple[frozenset[str], timedelta]] = {}
        for zone in zones:
            after_types = zone.get("dedupe_after_zone_types")
            if not after_types:
                continue
            window = timedelta(
                seconds=float(
                    zone.get(
                        "dedupe_after_seconds",
                        cfg.get("dedupe_after_seconds", 15.0),
                    )
                )
            )
            self._dedupe_after[zone["zone_id"]] = (frozenset(str(t) for t in after_types), window)

    @property
    def staff_zone_ids(self) -> set[str]:
        return self._staff_zone_ids

    @property
    def zone_id_to_type(self) -> dict[str, str]:
        return {z["zone_id"]: str(z["zone_type"]) for z in self._zones}

    def should_suppress_point(self, px: float, py: float) -> bool:
        return any(point_in_polygon(px, py, poly) for poly in self._exclude_polygons)

    def _prior_zone_requirement_met(
        self,
        track: TrackState,
        zone: dict[str, Any],
    ) -> bool:
        required = zone.get("require_prior_zone_types")
        if not required:
            return True
        return any(str(t) in track.last_zone_enter_at for t in required)

    def _should_suppress_duplicate_enter(
        self,
        track: TrackState,
        zone: dict[str, Any],
        *,
        now: datetime,
        emitted_zone_types: set[str] | None = None,
    ) -> bool:
        spec = self._dedupe_after.get(zone["zone_id"])
        if spec is None:
            return False
        after_types, window = spec
        if emitted_zone_types and after_types & emitted_zone_types:
            return True
        for zone_type, entered_at in track.last_zone_enter_at.items():
            if zone_type not in after_types:
                continue
            if now - entered_at <= window:
                return True
        return False

    def _should_suppress_same_type_enter(
        self,
        track: TrackState,
        zone_type: str,
        *,
        now: datetime,
    ) -> bool:
        last_at = track.last_zone_enter_at.get(zone_type)
        if last_at is None:
            return False
        return now - last_at <= self._same_type_debounce

    def _record_zone_enter(self, track: TrackState, zone_type: str, *, now: datetime) -> None:
        track.last_zone_enter_at[zone_type] = now

    def analyze(
        self,
        track: TrackState,
        *,
        now: datetime,
        prev_tracks: dict[int, TrackState],
    ) -> list[ZoneTransition]:
        transitions: list[ZoneTransition] = []
        emitted_zone_types: set[str] = set()
        px, py = track.foot_point
        prev = prev_tracks.get(track.local_track_id)
        if prev is not None:
            for zid, sign in prev.line_side_sign.items():
                track.line_side_sign.setdefault(zid, sign)
        for zid, sign in self._line_state.items():
            track.line_side_sign.setdefault(zid, sign)

        for zone in self._zones:
            zid = zone["zone_id"]
            kind = zone.get("kind", "polygon")

            if kind == "polygon":
                enter_poly = zone["points"]
                stay_poly = scale_polygon(
                    zone["points"], self._polygon_hysteresis, inward=True
                )
                inside_enter = point_in_polygon(px, py, enter_poly)
                inside_stay = point_in_polygon(px, py, stay_poly)
                was_inside = zid in track.zones_inside
                if inside_enter and not was_inside:
                    if not self._prior_zone_requirement_met(track, zone):
                        continue
                    if self._should_suppress_duplicate_enter(
                        track, zone, now=now, emitted_zone_types=emitted_zone_types
                    ):
                        track.zones_inside.add(zid)
                        track.zone_entered_at[zid] = now
                        continue
                    if self._should_suppress_same_type_enter(
                        track, zone["zone_type"], now=now
                    ):
                        track.zones_inside.add(zid)
                        track.zone_entered_at[zid] = now
                        continue
                    track.zones_inside.add(zid)
                    track.zone_entered_at[zid] = now
                    self._record_zone_enter(track, zone["zone_type"], now=now)
                    emitted_zone_types.add(zone["zone_type"])
                    transitions.append(
                        ZoneTransition(
                            event_type="vision.zone.entered",
                            zone_id=zid,
                            zone_name=zone["name"],
                            zone_type=zone["zone_type"],
                        )
                    )
                elif not inside_stay and was_inside:
                    entered_at = track.zone_entered_at.get(zid, now)
                    dwell_ms = int((now - entered_at).total_seconds() * 1000)
                    if dwell_ms < self._min_dwell_exit_ms:
                        continue
                    track.zones_inside.discard(zid)
                    track.zone_entered_at.pop(zid, None)
                    transitions.append(
                        ZoneTransition(
                            event_type="vision.zone.exited",
                            zone_id=zid,
                            zone_name=zone["name"],
                            zone_type=zone["zone_type"],
                            dwell_ms=dwell_ms,
                        )
                    )
                elif inside_stay and was_inside:
                    track.zones_inside.add(zid)

            elif kind == "line":
                if zone.get("counting_only"):
                    continue
                p1, p2 = zone["points"][0], zone["points"][1]
                normal = zone.get("direction_normal")
                side = line_side_value(px, py, p1, p2, normal)
                prev_raw = prev.line_side.get(zid) if prev else None
                track.line_side[zid] = side
                if prev_raw is None and zid not in track.line_side_sign:
                    init_sign = line_side_sign(side, self._line_hysteresis)
                    if init_sign != 0:
                        track.line_side_sign[zid] = init_sign
                        self._line_state[zid] = init_sign
                    continue

                curr_sign = line_side_sign(side, self._line_hysteresis)
                if curr_sign == 0:
                    continue
                prev_sign = track.line_side_sign.get(zid, 0)
                if prev_sign == 0:
                    track.line_side_sign[zid] = curr_sign
                    self._line_state[zid] = curr_sign
                    continue
                if prev_sign * curr_sign >= 0:
                    track.line_side_sign[zid] = curr_sign
                    self._line_state[zid] = curr_sign
                    continue

                last_cross = track.last_line_cross_at.get(zid)
                if last_cross is not None and now - last_cross < self._line_debounce:
                    track.line_side_sign[zid] = curr_sign
                    continue

                nx, ny = line_normal(p1, p2, normal)
                if prev is not None:
                    disp = abs(
                        (px - prev.foot_point[0]) * nx + (py - prev.foot_point[1]) * ny
                    )
                    if disp < self._min_line_displacement:
                        continue

                direction = "in" if curr_sign > prev_sign else "out"
                if self._should_suppress_same_type_enter(
                    track, zone["zone_type"], now=now
                ) and direction == "in":
                    track.last_line_cross_at[zid] = now
                    track.line_side_sign[zid] = curr_sign
                    continue

                track.last_line_cross_at[zid] = now
                track.line_side_sign[zid] = curr_sign
                self._line_state[zid] = curr_sign
                self._record_zone_enter(track, zone["zone_type"], now=now)
                emitted_zone_types.add(zone["zone_type"])
                transitions.append(
                    ZoneTransition(
                        event_type="vision.zone.entered",
                        zone_id=zid,
                        zone_name=zone["name"],
                        zone_type=zone["zone_type"],
                        direction=direction,
                    )
                )

        return transitions


class CameraPipeline:
    """Per-camera detect → track → classify → zone → session hooks."""

    def __init__(
        self,
        *,
        camera_id: str,
        camera_role: str,
        store_id: str,
        detector: Any,
        tracker_cfg: dict[str, Any],
        reid_cfg: dict[str, Any],
        staff_cfg: dict[str, Any],
        session_cfg: dict[str, Any],
        overlap_dedup_cfg: dict[str, Any],
        zones: list[dict[str, Any]],
        zone_analysis_cfg: dict[str, Any] | None = None,
        zone_debouncer: ZoneEventDebouncer | None = None,
        gir: GlobalIdentityRegistry,
        sessions: SessionManager,
        embedder: AppearanceEmbedder,
        cross_camera_dedup: CrossCameraDedup | None = None,
        recovery: TrackRecoveryRegistry | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.camera_role = camera_role
        self._detector = detector
        self._tracker = ByteTrackAdapter(tracker_cfg)
        self._line_state: dict[str, int] = {}
        self._zone_analyzer = ZoneAnalyzer(
            zones, camera_role, zone_analysis_cfg, zone_debouncer, self._line_state
        )
        self._zone_debouncer = zone_debouncer
        self._staff = StaffClassifier(staff_cfg, camera_role)
        self._gir = gir
        self._sessions = sessions
        self._embedder = embedder
        self._session_cfg = session_cfg
        self._dedup = cross_camera_dedup or CrossCameraDedup({})
        self._recovery = recovery
        self._mock_visitor_embedding: np.ndarray | None = None
        if reid_cfg.get("mock_shared_visitor_embedding") and reid_cfg.get("_mock_mode"):
            dim = int(reid_cfg.get("embedding_dim", 512))
            vec = np.ones(dim, dtype=np.float32)
            self._mock_visitor_embedding = (vec / np.linalg.norm(vec)).astype(np.float32)
        self._min_crop_h = float(reid_cfg.get("min_crop_height_px", 80)) / 1080.0
        self._track_index: dict[int, TrackState] = {}
        self._prev_index: dict[int, TrackState] = {}

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        *,
        frame_index: int,
        frame_timestamp: datetime,
    ) -> FramePipelineResult:
        self._prev_index = {k: _copy_track(v) for k, v in self._track_index.items()}

        raw = self._detector.detect(frame_bgr)
        tracked = self._tracker.update(frame_bgr, raw)

        active_ids = {tid for tid, _ in tracked}
        ended = [self._track_index[tid] for tid in list(self._track_index) if tid not in active_ids]
        if self._recovery is not None:
            for track in ended:
                self._recovery.register_lost(track, at=frame_timestamp)
        for tid in list(self._track_index):
            if tid not in active_ids:
                del self._track_index[tid]

        transitions: list[tuple[TrackState, ZoneTransition]] = []
        current_tracks: list[TrackState] = []

        for local_id, det in tracked:
            foot = bbox_foot_point(det.bbox_xywh)
            if self._zone_analyzer.should_suppress_point(foot[0], foot[1]):
                continue

            state = self._track_index.get(local_id)
            if state is None:
                role_hint = "staff" if self._staff.is_backroom_camera() else "visitor"
                embedding = None
                if det.bbox_xywh[3] >= self._min_crop_h:
                    if self._mock_visitor_embedding is not None and role_hint == "visitor":
                        embedding = self._mock_visitor_embedding.copy()
                    else:
                        embedding = self._embedder.embed(frame_bgr, det.bbox_xywh)
                global_id = self._gir.resolve(
                    camera_id=self.camera_id,
                    local_track_id=local_id,
                    embedding=embedding,
                    now=frame_timestamp,
                    role_hint=role_hint,
                    foot_point=foot,
                )
                state = TrackState(
                    local_track_id=local_id,
                    global_id=global_id,
                    camera_id=self.camera_id,
                    bbox_xywh=det.bbox_xywh,
                    confidence=det.confidence,
                    foot_point=foot,
                    first_seen=frame_timestamp,
                    embedding=embedding,
                )
                active = self._sessions.get_active(global_id)
                if active is not None:
                    state.session_id = active.session_id
                elif self._recovery is not None:
                    recovered_session = self._sessions.attach_recovered(
                        global_id, session_id=None, at=frame_timestamp
                    )
                    if recovered_session is not None:
                        state.session_id = recovered_session
                self._track_index[local_id] = state
            else:
                state.bbox_xywh = det.bbox_xywh
                state.confidence = det.confidence
                state.foot_point = foot
                if state.session_id is None:
                    active = self._sessions.get_active(state.global_id)
                    if active is not None:
                        state.session_id = active.session_id
                if det.bbox_xywh[3] >= self._min_crop_h:
                    if self._mock_visitor_embedding is not None and not state.is_staff:
                        state.embedding = self._mock_visitor_embedding.copy()
                    else:
                        state.embedding = self._embedder.embed(frame_bgr, det.bbox_xywh)

            state.last_seen = frame_timestamp
            self._staff.update_movement(state)

            zone_transitions_raw = self._zone_analyzer.analyze(
                state, now=frame_timestamp, prev_tracks=self._prev_index
            )
            for trans in zone_transitions_raw:
                if trans.event_type == "vision.zone.entered":
                    self._staff.record_zone_enter(state, trans.zone_type)

            was_staff = state.is_staff
            self._staff.update_track(
                state,
                frame_bgr,
                now=frame_timestamp,
                staff_zone_ids=self._zone_analyzer.staff_zone_ids,
                zone_id_to_type=self._zone_analyzer.zone_id_to_type,
            )
            if state.is_staff and not was_staff:
                self._gir.mark_role(state.global_id, "staff")
                self._sessions.mark_staff(state.global_id, at=frame_timestamp)
                state.session_id = None

            for trans in zone_transitions_raw:
                if (
                    self._zone_debouncer is not None
                    and trans.event_type == "vision.zone.entered"
                    and self._zone_debouncer.should_suppress_enter(
                        state.global_id, trans.zone_id, now=frame_timestamp
                    )
                ):
                    continue
                if self._dedup.should_suppress(state, trans, frame_timestamp):
                    trans.suppressed = True
                    continue
                self._dedup.record(state, trans, frame_timestamp)
                self._apply_session_rules(state, trans, frame_timestamp)
                if self._zone_debouncer is not None and trans.event_type == "vision.zone.entered":
                    self._zone_debouncer.record_enter(
                        state.global_id, trans.zone_id, now=frame_timestamp
                    )
                transitions.append((state, trans))

            current_tracks.append(state)

        return FramePipelineResult(
            camera_id=self.camera_id,
            frame_index=frame_index,
            frame_timestamp=frame_timestamp,
            tracks=current_tracks,
            zone_transitions=transitions,
            ended_tracks=ended,
        )

    def _apply_session_rules(
        self,
        track: TrackState,
        trans: ZoneTransition,
        now: datetime,
    ) -> None:
        if track.is_staff and trans.zone_type not in ("staff_only",):
            return

        if (
            trans.event_type == "vision.zone.entered"
            and trans.zone_type == "entry_threshold"
            and trans.direction == "in"
        ):
            session, is_reentry = self._sessions.start_or_resume(
                track.global_id, at=now, is_store_entry=True
            )
            track.session_id = session.session_id
            trans.is_reentry = is_reentry
        elif (
            trans.event_type == "vision.zone.entered"
            and trans.zone_type == "entry_threshold"
            and trans.direction == "out"
        ):
            trans.is_store_exit = True
            if self._session_cfg.get("end_on_store_exit", True):
                self._sessions.end(track.global_id, at=now)
                track.session_id = None
        elif trans.event_type == "vision.zone.entered" and track.session_id is None:
            if self.camera_role == "entry" and trans.zone_type in (
                "entrance",
                "entry_threshold",
            ):
                session, is_reentry = self._sessions.start_or_resume(
                    track.global_id, at=now, is_store_entry=trans.zone_type == "entry_threshold"
                )
                track.session_id = session.session_id
                trans.is_reentry = is_reentry


def _copy_track(track: TrackState) -> TrackState:
    return TrackState(
        local_track_id=track.local_track_id,
        global_id=track.global_id,
        camera_id=track.camera_id,
        bbox_xywh=track.bbox_xywh,
        confidence=track.confidence,
        foot_point=track.foot_point,
        is_staff=track.is_staff,
        class_label=track.class_label,
        session_id=track.session_id,
        zones_inside=set(track.zones_inside),
        line_side=dict(track.line_side),
        line_side_sign=dict(track.line_side_sign),
        dark_uniform_frames=track.dark_uniform_frames,
        zone_entered_at=dict(track.zone_entered_at),
        last_line_cross_at=dict(track.last_line_cross_at),
        last_zone_enter_at=dict(track.last_zone_enter_at),
        first_seen=track.first_seen,
        last_seen=track.last_seen,
        embedding=track.embedding.copy() if track.embedding is not None else None,
        foot_point_history=list(track.foot_point_history),
        path_length=track.path_length,
        zone_type_visits=list(track.zone_type_visits),
        staff_reason=track.staff_reason,
    )


class MultiCameraPipeline:
    """Orchestrates all camera pipelines sharing GIR and SessionManager."""

    def __init__(self, config: Any, detector: Any) -> None:
        self._cfg = config
        self._embedder = AppearanceEmbedder(int(config.reid.get("embedding_dim", 512)))
        self._recovery = TrackRecoveryRegistry(config.reid)
        reid_cfg = dict(config.reid)
        if str(config.detector.get("mode", "yolo")).lower() == "mock":
            reid_cfg["_mock_mode"] = True
            reid_cfg.setdefault("mock_shared_visitor_embedding", True)
        self._gir = GlobalIdentityRegistry(
            config.store_id,
            reid_cfg=reid_cfg,
            camera_graph=config.camera_graph,
            camera_roles={cam.id: cam.role for cam in config.cameras},
            recovery=self._recovery,
        )
        self._sessions = SessionManager(config.store_id, config.session)
        self._dedup = CrossCameraDedup(config.overlap_dedup)
        self._zone_debouncer = ZoneEventDebouncer(config.zone_analysis)
        self._pipelines: dict[str, CameraPipeline] = {}
        tracker_cfg = dict(config.tracker)
        sample_fps = float(config.processing.get("sample_fps", 5.0))
        tracker_cfg.setdefault("frame_rate", max(int(round(sample_fps)), 1))
        tracker_cfg.setdefault(
            "track_buffer",
            max(int(round(sample_fps * 12)), 30),
        )
        if str(config.detector.get("mode", "yolo")).lower() == "mock":
            tracker_cfg["match_thresh"] = float(
                config.tracker.get("mock_match_thresh", 0.48)
            )
            tracker_cfg["track_thresh"] = float(
                config.tracker.get("mock_track_thresh", 0.22)
            )
            tracker_cfg["track_buffer"] = int(
                config.tracker.get("mock_track_buffer", 100)
            )

        for cam in config.cameras:
            zones = config.zones_by_camera.get(cam.id, [])
            cam_detector = (
                detector[cam.id]
                if isinstance(detector, dict)
                else detector
            )
            self._pipelines[cam.id] = CameraPipeline(
                camera_id=cam.id,
                camera_role=cam.role,
                store_id=config.store_id,
                detector=cam_detector,
                tracker_cfg=tracker_cfg,
                reid_cfg=reid_cfg,
                staff_cfg=config.staff,
                session_cfg=config.session,
                overlap_dedup_cfg=config.overlap_dedup,
                zones=zones,
                zone_analysis_cfg=getattr(config, "zone_analysis", {}),
                zone_debouncer=self._zone_debouncer,
                gir=self._gir,
                sessions=self._sessions,
                embedder=self._embedder,
                cross_camera_dedup=self._dedup,
                recovery=self._recovery,
            )

    @property
    def sessions(self) -> SessionManager:
        return self._sessions

    def pipeline_for(self, camera_id: str) -> CameraPipeline:
        return self._pipelines[camera_id]
