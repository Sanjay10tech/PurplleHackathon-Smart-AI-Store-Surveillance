"""Bootstrap POS CSV ingestion on application startup."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.config import Settings, get_settings
from app.database import create_session_factory
from app.logging_config import get_logger
from app.services.pos_ingestion_service import PosIngestionService

logger = get_logger(__name__)


async def bootstrap_pos_ingestion(settings: Settings | None = None) -> dict:
    """Idempotent POS ingest + CCTV correlation + PURCHASE events."""
    cfg = settings or get_settings()
    if not cfg.pos_auto_ingest:
        return {"skipped": True, "reason": "pos_auto_ingest disabled"}

    csv_path = Path(cfg.pos_csv_path)
    if not csv_path.is_file():
        logger.warning("pos_csv_missing", path=str(csv_path))
        return {"skipped": True, "reason": f"CSV not found: {csv_path}"}

    store_id = UUID(cfg.pos_store_id)
    session_factory = create_session_factory()
    async with session_factory() as session:
        service = PosIngestionService(session, cfg)
        result = await service.ingest_store_pos(
            store_id,
            csv_path=csv_path,
            replace_existing=False,
            link_journeys=True,
            emit_purchase_events=True,
        )
    return {
        "skipped": False,
        "orders_parsed": result.orders_parsed,
        "transactions_inserted": result.transactions_inserted,
        "sessions_linked": result.sessions_linked,
        "purchase_events": result.purchase_events_created,
        "revenue_nmv": str(result.revenue_nmv),
    }
