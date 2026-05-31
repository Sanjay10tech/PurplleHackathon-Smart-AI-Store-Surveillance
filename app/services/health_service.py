"""
Health service — liveness, database connectivity, and vision feed freshness.

Assumptions
-----------
1. **Feed freshness** uses the latest `vision.frame.processed` or
   `vision.zone.entered` event across all stores (global pipeline health).

2. **STALE_FEED** when minutes since last feed event ≥ `health_stale_feed_minutes`
   (default 15). Status becomes `degraded`; database down → `unhealthy`.

3. **No events ever** → `feed=unknown`, `stale_feed=true`, status `degraded`.

4. Thresholds align with anomaly STALE_FEED defaults but are configured via
   `health_stale_feed_minutes` on Settings (not per-store).
"""

from datetime import UTC, datetime

from app.config import Settings
from app.database import check_database_connection
from app.logging_config import get_logger
from app.repositories.interfaces import HealthRepositoryProtocol
from app.schemas.health import HealthChecks, HealthResponse

logger = get_logger(__name__)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class HealthService:
    def __init__(
        self,
        health_repository: HealthRepositoryProtocol,
        settings: Settings,
    ) -> None:
        self._health = health_repository
        self._settings = settings

    async def get_health(self) -> tuple[HealthResponse, int]:
        """
        Build health report and suggested HTTP status.

        Returns (response, http_status) where 503 only when database is down.
        """
        db_ok = await check_database_connection()
        last_event_at = await self._health.get_last_feed_event_at()
        now = datetime.now(tz=UTC)

        feed_stale_minutes: float | None = None
        stale_feed = False
        feed_status = "unknown"

        if last_event_at is not None:
            last_event_at = _as_utc(last_event_at)
            feed_stale_minutes = round((now - last_event_at).total_seconds() / 60.0, 2)
            if feed_stale_minutes >= self._settings.health_stale_feed_minutes:
                stale_feed = True
                feed_status = "stale"
            else:
                feed_status = "fresh"
        else:
            stale_feed = True

        if not db_ok:
            status = "unhealthy"
            http_status = 503
        elif stale_feed:
            status = "degraded"
            http_status = 200
        else:
            status = "ok"
            http_status = 200

        response = HealthResponse(
            status=status,
            service=self._settings.app_name,
            version=self._settings.app_version,
            checks=HealthChecks(
                database="up" if db_ok else "down",
                feed=feed_status,
            ),
            last_event_at=last_event_at,
            feed_stale_minutes=feed_stale_minutes,
            stale_feed=stale_feed,
        )

        logger.info(
            "health_check_completed",
            status=status,
            database=response.checks.database,
            feed=feed_status,
            stale_feed=stale_feed,
            feed_stale_minutes=feed_stale_minutes,
            last_event_at=last_event_at.isoformat() if last_event_at else None,
        )

        return response, http_status

    async def get_readiness(self) -> tuple[str, dict[str, str], bool]:
        """Readiness probe — database must be up."""
        db_ok = await check_database_connection()
        checks = {"database": "up" if db_ok else "down"}
        ready = db_ok
        return ("ready" if ready else "not_ready", checks, ready)
