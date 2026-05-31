"""Post-ingest journey wiring for reviewer demo metrics (sessions + POS linkage)."""

from __future__ import annotations

from uuid import UUID

from app.config import Settings, get_settings
from app.database import create_session_factory
from app.logging_config import get_logger
from app.services.pos_ingestion_service import PosIngestionService
from app.services.visit_session_materializer import materialize_visit_sessions

logger = get_logger(__name__)


async def ensure_reviewer_journey_metrics(settings: Settings | None = None) -> dict:
    """Materialize CCTV sessions and re-link POS after vision events are present."""
    cfg = settings or get_settings()
    store_id = UUID(cfg.cctv_store_id)
    session_factory = create_session_factory()

    async with session_factory() as session:
        materialized = await materialize_visit_sessions(session, store_id)
        pos = PosIngestionService(session, cfg)
        linked = await pos.recorrelate_journeys(store_id)
        purchase_synced = await pos.sync_purchase_event_tracks(store_id)
        await session.commit()

    stats = {
        **materialized,
        "pos_journeys_linked": linked,
        "purchase_events_synced": purchase_synced,
    }
    logger.info("reviewer_journey_metrics_ready", **stats)
    return stats
