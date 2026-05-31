#!/usr/bin/env python3
"""Extended funnel audit — staff, re-entry, session vs track paths, unmapped zones."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")


async def main() -> None:
    from sqlalchemy import text

    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = url
    reset_engine_singleton()
    engine = create_engine()
    sf = create_session_factory(engine)
    store = str(DEMO_STORE_ID)

    async with sf() as session:
        staff = await session.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT payload->>'external_track_id') AS tracks
                FROM events
                WHERE store_id = :store
                  AND event_type = 'vision.zone.entered'
                  AND (
                    payload->>'class_label' = 'staff'
                    OR payload->>'zone_type' IN ('staff_only', 'ignore')
                  )
                """
            ),
            {"store": store},
        )
        print("Staff/ignore zone events:", dict(staff.one()._mapping))

        entry_zones = await session.execute(
            text(
                """
                SELECT COUNT(*) AS raw,
                       COUNT(DISTINCT payload->>'external_track_id') AS tracks
                FROM events
                WHERE store_id = :store
                  AND event_type = 'vision.zone.entered'
                  AND payload->>'zone_type' IN ('entry_threshold', 'entrance', 'entry')
                  AND COALESCE(payload->>'class_label', '') != 'staff'
                """
            ),
            {"store": store},
        )
        print("Entry zone events (customer):", dict(entry_zones.one()._mapping))

        sessions = await session.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (
                         WHERE COALESCE(metadata->>'staff', 'false') != 'true'
                       ) AS customer
                FROM sessions WHERE store_id = :store
                """
            ),
            {"store": store},
        )
        print("Sessions:", dict(sessions.one()._mapping))

        zone_types = await session.execute(
            text(
                """
                SELECT payload->>'zone_type' AS zone_type,
                       COUNT(*) AS events,
                       COUNT(DISTINCT payload->>'external_track_id') AS tracks
                FROM events
                WHERE store_id = :store
                  AND event_type = 'vision.zone.entered'
                  AND COALESCE(payload->>'class_label', '') != 'staff'
                  AND COALESCE(payload->>'zone_type', '') NOT IN ('staff_only', 'ignore')
                GROUP BY 1
                ORDER BY events DESC
                """
            ),
            {"store": store},
        )
        print("\nZone types (customer):")
        for row in zone_types:
            print(" ", dict(row._mapping))

        multi_entry = await session.execute(
            text(
                """
                SELECT payload->>'external_track_id' AS track_id, COUNT(*) AS enters
                FROM events
                WHERE store_id = :store
                  AND event_type = 'vision.zone.entered'
                  AND payload->>'zone_type' = 'entry_threshold'
                  AND COALESCE(payload->>'class_label', '') != 'staff'
                GROUP BY 1
                HAVING COUNT(*) > 1
                ORDER BY enters DESC
                LIMIT 10
                """
            ),
            {"store": store},
        )
        print("\nMulti entry_threshold re-entries in raw data:")
        for row in multi_entry:
            print(" ", dict(row._mapping))

        purchases = await session.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM events
                   WHERE store_id = :store
                     AND event_type = 'analytics.purchase.completed') AS purchase_events,
                  (SELECT COUNT(*) FROM transactions
                   WHERE store_id = :store AND status = 'completed') AS completed_tx
                """
            ),
            {"store": store},
        )
        print("\nPurchase sources:", dict(purchases.one()._mapping))

        unmapped = await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT payload->>'external_track_id') AS tracks
                FROM events
                WHERE store_id = :store
                  AND event_type = 'vision.zone.entered'
                  AND COALESCE(payload->>'class_label', '') != 'staff'
                  AND payload->>'zone_type' IN ('browse_skincare', 'browse_cosmetics')
                """
            ),
            {"store": store},
        )
        print("browse_skincare/cosmetics distinct tracks (currently unmapped):", unmapped.scalar())

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
