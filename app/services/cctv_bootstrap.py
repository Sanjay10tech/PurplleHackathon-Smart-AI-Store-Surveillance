"""Bootstrap CCTV vision events on first boot (idempotent)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.database import create_session_factory
from app.logging_config import get_logger
from app.models import Event
from app.repositories.event_repository import EventRepository
from app.repositories.store_repository import StoreRepository
from app.services.event_ingestion_service import EventIngestionService
from app.services.event_validation_service import EventValidationService
from app.services.metrics_projector_service import MetricsProjectorService

logger = get_logger(__name__)

DEFAULT_BOOTSTRAP = Path("data/reviewer/yolo_bootstrap_events.jsonl")
VISION_EVENT_TYPES = (
    "vision.frame.processed",
    "vision.zone.entered",
    "vision.zone.exited",
    "vision.track.started",
    "vision.track.ended",
    "vision.session.started",
    "vision.session.ended",
)


async def _vision_event_count(session, store_id: UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type.in_(VISION_EVENT_TYPES),
        )
    )
    return int(result.scalar() or 0)


def _normalize_bootstrap_path(path: Path) -> Path:
    if path.is_file():
        return path
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / path
    return candidate if candidate.is_file() else path


async def bootstrap_cctv_events(settings: Settings | None = None) -> dict:
    """Load committed YOLO bootstrap events when the store has no CCTV data."""
    cfg = settings or get_settings()
    if not cfg.cctv_auto_bootstrap:
        return {"skipped": True, "reason": "cctv_auto_bootstrap disabled"}

    store_id = UUID(cfg.cctv_store_id)
    bootstrap_path = _normalize_bootstrap_path(Path(cfg.cctv_bootstrap_path))
    session_factory = create_session_factory()

    async with session_factory() as session:
        existing = await _vision_event_count(session, store_id)
        result: dict[str, object] = {
            "skipped": existing >= cfg.cctv_bootstrap_min_events,
            "vision_events": existing,
        }

        if existing < cfg.cctv_bootstrap_min_events:
            if not bootstrap_path.is_file():
                logger.warning("cctv_bootstrap_missing", path=str(bootstrap_path))
                result["reason"] = f"bootstrap file missing: {bootstrap_path}"
            else:
                events: list[dict] = []
                with bootstrap_path.open(encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        events.append(json.loads(line))

                if not events:
                    result["reason"] = "bootstrap file empty"
                else:
                    ingestion = EventIngestionService(
                        EventRepository(session),
                        EventValidationService(StoreRepository(session)),
                        cfg,
                        MetricsProjectorService(session)
                        if cfg.metrics_projector_enabled
                        else None,
                    )
                    from app.schemas.events import EventBatchIngestRequest, EventIngestRequest

                    batch = EventBatchIngestRequest(
                        events=[EventIngestRequest.model_validate(item) for item in events]
                    )
                    response = await ingestion.ingest_batch(batch, correlation_id="cctv-bootstrap")
                    result.update(
                        {
                            "skipped": False,
                            "bootstrap_file": bootstrap_path.name,
                            "events_in_file": len(events),
                            "accepted": response.summary.accepted,
                            "duplicate": response.summary.duplicate,
                            "rejected": response.summary.rejected,
                        }
                    )

        from app.services.visit_session_materializer import materialize_visit_sessions

        materialized = await materialize_visit_sessions(session, store_id)
        await session.commit()
        result.update(materialized)
        result["vision_events_after"] = await _vision_event_count(session, store_id)
        return result
