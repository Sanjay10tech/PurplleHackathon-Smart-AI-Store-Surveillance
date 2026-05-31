"""Block until PostgreSQL accepts connections (Docker startup)."""

import asyncio
import os
import sys

from app.config import get_settings
from app.database import check_database_connection, create_engine, reset_engine_singleton
from app.logging_config import get_logger

logger = get_logger(__name__)


async def wait_for_database() -> None:
    max_attempts = int(os.environ.get("DB_WAIT_MAX_ATTEMPTS", "30"))
    interval = float(os.environ.get("DB_WAIT_INTERVAL_SECONDS", "2"))

    get_settings.cache_clear()
    reset_engine_singleton()
    create_engine(get_settings())

    for attempt in range(1, max_attempts + 1):
        if await check_database_connection():
            logger.info(
                "database_ready",
                attempt=attempt,
                max_attempts=max_attempts,
            )
            return

        logger.warning(
            "database_not_ready",
            attempt=attempt,
            max_attempts=max_attempts,
            retry_in_seconds=interval,
        )
        await asyncio.sleep(interval)

    logger.error("database_wait_timeout", max_attempts=max_attempts)
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(wait_for_database())
