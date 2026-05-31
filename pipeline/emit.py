"""Build and deliver domain events matching app/schemas/events.py."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from pipeline.ingest import PipelineIngestClient, partition_batches, validate_event_dicts
from pipeline.tracker import FramePipelineResult, SessionRecord, TrackState, ZoneTransition


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


class EventBuilder:
    """Maps pipeline outputs to ingest-ready event dicts."""

    def __init__(
        self,
        *,
        store_id: str,
        tenant_id: str,
        schema_version: str,
        pipeline_run_id: uuid.UUID,
        correlation_id: str,
        detector_mode: str = "yolo",
    ) -> None:
        self.store_id = store_id
        self.tenant_id = tenant_id
        self.schema_version = schema_version
        self.pipeline_run_id = pipeline_run_id
        self.correlation_id = correlation_id
        self.detector_mode = detector_mode

    def frame_processed(
        self,
        result: FramePipelineResult,
        *,
        processing_ms: int,
        source_video: str | None = None,
    ) -> dict[str, Any]:
        detections = []
        tracks = []
        for track in result.tracks:
            det_id = uuid.uuid4()
            x, y, w, h = track.bbox_xywh
            detections.append(
                {
                    "detection_id": str(det_id),
                    "class_external_id": track.class_label,
                    "bbox": {"x": x, "y": y, "w": w, "h": h, "space": "normalized"},
                    "confidence": track.confidence,
                }
            )
            tracks.append(
                {
                    "track_id": str(uuid.uuid4()),
                    "track_id_ext": track.local_track_id,
                    "detection_id": str(det_id),
                    "state": "active",
                    "external_track_id": track.global_id,
                }
            )

        return self._envelope(
            event_type="vision.frame.processed",
            aggregate_type="pipeline_run",
            aggregate_id=self.pipeline_run_id,
            occurred_at=result.frame_timestamp,
            idempotency_key=(
                f"frame-{result.camera_id}-{result.frame_index}-{self.pipeline_run_id}"
            ),
            payload={
                "pipeline_run_id": str(self.pipeline_run_id),
                "camera_id": result.camera_id,
                "frame_index": result.frame_index,
                "frame_timestamp": _iso(result.frame_timestamp),
                "detections": detections,
                "tracks": tracks,
                "processing_ms": processing_ms,
                "detector_mode": self.detector_mode,
                "source_video": source_video,
            },
        )

    def zone_event(
        self,
        track: TrackState,
        transition: ZoneTransition,
        *,
        occurred_at: datetime,
    ) -> dict[str, Any] | None:
        if track.is_staff and transition.zone_type not in ("staff_only", "ignore"):
            return None
        if transition.zone_type == "ignore":
            return None

        payload: dict[str, Any] = {
            "zone_id": transition.zone_id,
            "zone_name": transition.zone_name,
            "zone_type": transition.zone_type,
            "camera_id": track.camera_id,
            "external_track_id": track.global_id,
            "class_label": track.class_label,
            "position": {
                "x": track.foot_point[0],
                "y": track.foot_point[1],
                "space": "normalized",
            },
        }
        if track.session_id is not None:
            payload["session_id"] = str(track.session_id)
        if transition.direction:
            payload["direction"] = transition.direction
        if transition.dwell_ms is not None:
            payload["dwell_ms"] = transition.dwell_ms
        if transition.is_reentry:
            payload["is_reentry"] = True
        if transition.is_store_exit:
            payload["is_store_exit"] = True
        if transition.direction == "in" and transition.zone_type in ("entry_threshold", "entrance"):
            payload["is_store_entry"] = True
        payload["detector_mode"] = self.detector_mode

        return self._envelope(
            event_type=transition.event_type,
            aggregate_type="zone",
            aggregate_id=uuid.uuid5(uuid.NAMESPACE_URL, transition.zone_id),
            occurred_at=occurred_at,
            idempotency_key=(
                f"{transition.event_type}-{track.global_id}-{transition.zone_id}-"
                f"{int(occurred_at.timestamp() * 1000)}"
            ),
            payload=payload,
        )

    def track_ended(self, track: TrackState, *, occurred_at: datetime) -> dict[str, Any]:
        return self._envelope(
            event_type="vision.track.ended",
            aggregate_type="track",
            aggregate_id=uuid.uuid5(uuid.NAMESPACE_URL, track.global_id),
            occurred_at=occurred_at,
            idempotency_key=f"track-ended-{track.global_id}-{track.camera_id}-{track.local_track_id}",
            payload={
                "camera_id": track.camera_id,
                "external_track_id": track.global_id,
                "local_track_id": track.local_track_id,
                "first_seen": _iso(track.first_seen) if track.first_seen else None,
                "last_seen": _iso(track.last_seen) if track.last_seen else None,
                "class_label": track.class_label,
                "session_id": str(track.session_id) if track.session_id else None,
                "detector_mode": self.detector_mode,
            },
        )

    def _envelope(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        occurred_at: datetime,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        body = dict(payload)
        body.setdefault("store_id", self.store_id)
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "occurred_at": _iso(occurred_at),
            "correlation_id": self.correlation_id,
            "idempotency_key": idempotency_key,
            "aggregate": {"type": aggregate_type, "id": str(aggregate_id)},
            "payload": body,
        }


class EventEmitter:
    """Collect events, write JSONL, optionally POST to API and persist sessions."""

    def __init__(self, emit_cfg: dict[str, Any], *, store_id: str, tenant_id: str) -> None:
        self._cfg = emit_cfg
        self._store_id = store_id
        self._tenant_id = tenant_id
        self._events: list[dict[str, Any]] = []

    @property
    def events(self) -> list[dict[str, Any]]:
        return self._events

    def add(self, event: dict[str, Any] | None) -> None:
        if event is not None:
            self._events.append(event)

    def extend(self, events: list[dict[str, Any]]) -> None:
        self._events.extend(events)

    def write_jsonl(self, path: str | Path | None = None) -> Path:
        out = Path(path or self._cfg.get("output_jsonl", "data/pipeline/events.jsonl"))
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for event in self._events:
                fh.write(json.dumps(event) + "\n")
        return out

    def write_sessions_jsonl(
        self,
        sessions: list[SessionRecord],
        path: str | Path | None = None,
    ) -> Path:
        out = Path(path or self._cfg.get("output_sessions_jsonl", "data/pipeline/sessions.jsonl"))
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for session in sessions:
                row = {
                    "session_id": str(session.session_id),
                    "store_id": session.store_id,
                    "external_track_id": session.external_track_id,
                    "started_at": _iso(session.started_at),
                    "ended_at": _iso(session.ended_at) if session.ended_at else None,
                    "status": session.status,
                    "is_reentry": session.is_reentry,
                    "metadata": session.metadata,
                }
                fh.write(json.dumps(row) + "\n")
        return out

    async def post_to_api(self, api_url: str | None = None, batch_size: int = 100) -> dict[str, Any]:
        url = api_url or self._cfg.get("api_url", "http://localhost:8000/api/v1/events/ingest")
        base_url = url.rsplit("/api/", 1)[0] if "/api/" in url else "http://localhost:8000"
        ingest_path = url[url.find("/api/") :] if "/api/" in url else "/api/v1/events/ingest"

        api_key = self._cfg.get("api_key") or os.environ.get("API_KEY")
        client = PipelineIngestClient(
            base_url=base_url,
            ingest_path=ingest_path,
            batch_size=batch_size,
            validate_before_post=bool(self._cfg.get("validate_before_post", True)),
            api_key=api_key or None,
        )
        return await client.ingest_events(self._events)

    @staticmethod
    def _tally_response(resp: httpx.Response, summary: dict[str, Any]) -> None:
        if resp.status_code in (200, 201, 202):
            body = resp.json()
            if body.get("duplicate"):
                summary["duplicate"] += 1
            else:
                summary["accepted"] += 1
        else:
            summary["rejected"] += 1

    def validate_all(self) -> list[str]:
        _, errors = validate_event_dicts(self._events)
        return errors

    @staticmethod
    def write_sample_files(output_dir: str | Path = "data/samples/events") -> dict[str, Path]:
        """Write reference event JSON files for manual ingest testing."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        store_id = "00000000-0000-0000-0000-000000000101"
        tenant_id = "00000000-0000-0000-0000-000000000001"
        now = datetime.now(tz=UTC)
        run_id = uuid.uuid4()
        builder = EventBuilder(
            store_id=store_id,
            tenant_id=tenant_id,
            schema_version="1.0.0",
            pipeline_run_id=run_id,
            correlation_id="sample-events",
        )

        from pipeline.tracker import FramePipelineResult, TrackState, ZoneTransition

        track = TrackState(
            local_track_id=1,
            global_id=f"{store_id}:{uuid.uuid4()}",
            camera_id="00000000-0000-0000-0000-000000000203",
            bbox_xywh=(0.42, 0.35, 0.08, 0.22),
            confidence=0.91,
            foot_point=(0.46, 0.57),
            session_id=uuid.uuid4(),
            class_label="visitor",
        )
        frame_event = builder.frame_processed(
            FramePipelineResult(
                camera_id=track.camera_id,
                frame_index=120,
                frame_timestamp=now,
                tracks=[track],
                zone_transitions=[],
                ended_tracks=[],
            ),
            processing_ms=42,
        )
        zone_enter = builder.zone_event(
            track,
            ZoneTransition(
                event_type="vision.zone.entered",
                zone_id="zone-cam3-entry-threshold",
                zone_name="entry_threshold",
                zone_type="entry_threshold",
                direction="in",
            ),
            occurred_at=now,
        )
        zone_exit = builder.zone_event(
            track,
            ZoneTransition(
                event_type="vision.zone.exited",
                zone_id="zone-cam1-browse-left",
                zone_name="browse_skincare_wall",
                zone_type="browse_skincare",
                dwell_ms=45_000,
            ),
            occurred_at=now + timedelta(seconds=60),
        )
        assert zone_enter is not None and zone_exit is not None

        paths: dict[str, Path] = {}
        singles = {
            "vision.frame.processed.json": frame_event,
            "vision.zone.entered.json": zone_enter,
            "vision.zone.exited.json": zone_exit,
        }
        for name, event in singles.items():
            path = out_dir / name
            path.write_text(json.dumps(event, indent=2), encoding="utf-8")
            paths[name] = path

        batch_path = out_dir / "batch_ingest.json"
        batch_path.write_text(
            json.dumps({"events": [frame_event, zone_enter, zone_exit]}, indent=2),
            encoding="utf-8",
        )
        paths["batch_ingest.json"] = batch_path
        return paths

    def post_to_api_sync(self, **kwargs: Any) -> dict[str, Any]:
        return asyncio.run(self.post_to_api(**kwargs))

    async def persist_sessions(self, sessions: list[SessionRecord], database_url: str | None = None) -> int:
        import os

        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        from pipeline.ingest import persist_sessions_to_db

        url = database_url or self._cfg.get("database_url") or os.environ.get("DATABASE_URL")
        if not url:
            return 0
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        engine = create_async_engine(url)
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        count = 0
        async with factory() as db:
            count = await persist_sessions_to_db(db, sessions)
            await db.commit()
        await engine.dispose()
        return count

    def persist_sessions_sync(self, sessions: list[SessionRecord], **kwargs: Any) -> int:
        return asyncio.run(self.persist_sessions(sessions, **kwargs))

    def flush(
        self,
        sessions: list[SessionRecord],
        *,
        batch_size: int = 100,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        results["events_path"] = str(self.write_jsonl())
        results["sessions_path"] = str(self.write_sessions_jsonl(sessions))
        results["event_count"] = len(self._events)
        results["session_count"] = len(sessions)

        validation_errors = self.validate_all()
        if validation_errors:
            results["validation_errors"] = validation_errors

        # Sessions must exist before vision events that reference session_id (FK).
        if self._cfg.get("persist_sessions"):
            results["sessions_persisted"] = self.persist_sessions_sync(sessions)
        if self._cfg.get("post_to_api"):
            results["api"] = self.post_to_api_sync(batch_size=batch_size)
        return results
