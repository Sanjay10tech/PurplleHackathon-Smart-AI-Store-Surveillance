"""Re-ID evidence service — cross-camera identity proof from ingested events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.reid.evidence import analyze_reid_evidence
from app.exceptions import NotFoundError
from app.logging_config import get_logger
from app.repositories.interfaces import EventRepositoryProtocol, StoreRepositoryProtocol
from app.schemas.reid import (
    CrossCameraTrackEvidence,
    HandoffCandidateEvidence,
    ReIdEvidenceResponse,
    TrackCameraPresence,
)

logger = get_logger(__name__)

CAMERA_GRAPH = [
    {"from": "00000000-0000-0000-0000-000000000201", "to": "00000000-0000-0000-0000-000000000205", "priority": "P0"},
    {"from": "00000000-0000-0000-0000-000000000202", "to": "00000000-0000-0000-0000-000000000205", "priority": "P0"},
    {"from": "00000000-0000-0000-0000-000000000203", "to": "00000000-0000-0000-0000-000000000201", "priority": "P0"},
    {"from": "00000000-0000-0000-0000-000000000203", "to": "00000000-0000-0000-0000-000000000202", "priority": "P0"},
    {"from": "00000000-0000-0000-0000-000000000205", "to": "00000000-0000-0000-0000-000000000204", "priority": "P1"},
]

CAMERA_NAMES = {
    "00000000-0000-0000-0000-000000000201": "CAM 1 (floor)",
    "00000000-0000-0000-0000-000000000202": "CAM 2 (floor)",
    "00000000-0000-0000-0000-000000000203": "CAM 3 (entry)",
    "00000000-0000-0000-0000-000000000204": "CAM 4 (backroom)",
    "00000000-0000-0000-0000-000000000205": "CAM 5 (billing)",
}


class ReIdEvidenceService:
    def __init__(
        self,
        event_repository: EventRepositoryProtocol,
        store_repository: StoreRepositoryProtocol,
    ) -> None:
        self._events = event_repository
        self._stores = store_repository

    async def get_evidence(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> ReIdEvidenceResponse:
        store = await self._stores.get_by_id(store_id)
        if store is None:
            raise NotFoundError("store", str(store_id))

        period_end = to_ts or datetime.now(tz=UTC)
        period_start = from_ts or (period_end - timedelta(hours=24))

        events = await self._events.list_by_store(
            store_id,
            from_ts=period_start,
            to_ts=period_end,
            limit=5000,
        )
        vision_events = [
            e for e in events
            if e.event_type.startswith("vision.") and (e.payload or {}).get("external_track_id")
        ]

        analysis = analyze_reid_evidence(
            vision_events,
            camera_names=CAMERA_NAMES,
            camera_graph=CAMERA_GRAPH,
        )

        cross_tracks = [
            CrossCameraTrackEvidence(
                external_track_id=t.external_track_id,
                track_suffix=t.track_suffix,
                cameras=[
                    TrackCameraPresence(
                        camera_id=c.camera_id,
                        camera_name=c.camera_name,
                        event_count=c.event_count,
                        first_seen=c.first_seen,
                        last_seen=c.last_seen,
                        zone_types=c.zone_types,
                    )
                    for c in t.cameras
                ],
                camera_count=t.camera_count,
                total_events=t.total_events,
                journey_path=t.journey_path,
            )
            for t in analysis["cross_camera_tracks"][:15]
        ]

        handoffs = [
            HandoffCandidateEvidence(
                from_track_id=h.from_track_id,
                to_track_id=h.to_track_id,
                from_camera=h.from_camera,
                to_camera=h.to_camera,
                from_camera_name=h.from_camera_name,
                to_camera_name=h.to_camera_name,
                gap_seconds=h.gap_seconds,
                graph_priority=h.graph_priority,
                reason=h.reason,
            )
            for h in analysis["handoff_candidates"][:10]
        ]

        logger.info(
            "reid_evidence_computed",
            store_id=str(store_id),
            unique_tracks=analysis["unique_track_ids"],
            cross_camera=analysis["cross_camera_count"],
        )

        return ReIdEvidenceResponse(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            unique_track_ids=analysis["unique_track_ids"],
            single_camera_tracks=analysis["single_camera_tracks"],
            cross_camera_track_count=analysis["cross_camera_count"],
            cross_camera_tracks=cross_tracks,
            handoff_candidates=handoffs,
            pipeline_strategy={
                "per_camera_tracker": "ByteTrack",
                "global_registry": "GlobalIdentityRegistry (GIR)",
                "embedding": "HSV histogram 512-d (AppearanceEmbedder)",
                "cross_camera_signals": [
                    "cosine similarity",
                    "camera graph P0/P1 handoff windows",
                    "time gap scoring",
                    "TrackRecoveryRegistry (same-camera ID switch)",
                    "P0 solo handoff (single active visitor on source cam)",
                ],
                "external_track_id_format": "{store_id}:{global_uuid}",
            },
            meta={
                "vision_events_analyzed": len(vision_events),
                "handoff_candidate_count": analysis["handoff_candidate_count"],
                "reid_enabled": True,
                "source": "reid_evidence_engine",
            },
        )
