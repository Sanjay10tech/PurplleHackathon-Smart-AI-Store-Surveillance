from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TrackCameraPresence(BaseModel):
    camera_id: str
    camera_name: str | None = None
    event_count: int
    first_seen: datetime
    last_seen: datetime
    zone_types: list[str] = Field(default_factory=list)


class CrossCameraTrackEvidence(BaseModel):
    external_track_id: str
    track_suffix: str
    cameras: list[TrackCameraPresence]
    camera_count: int
    total_events: int
    journey_path: str


class HandoffCandidateEvidence(BaseModel):
    from_track_id: str
    to_track_id: str
    from_camera: str
    to_camera: str
    from_camera_name: str | None = None
    to_camera_name: str | None = None
    gap_seconds: float
    graph_priority: str
    reason: str


class ReIdEvidenceResponse(BaseModel):
    store_id: UUID
    period_start: datetime
    period_end: datetime
    unique_track_ids: int
    single_camera_tracks: int
    cross_camera_track_count: int
    cross_camera_tracks: list[CrossCameraTrackEvidence]
    handoff_candidates: list[HandoffCandidateEvidence]
    pipeline_strategy: dict[str, Any]
    meta: dict[str, Any] = Field(default_factory=dict)
