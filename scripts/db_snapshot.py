#!/usr/bin/env python3
"""Quick DB snapshot for audit."""
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

STORE = "00000000-0000-0000-0000-000000000101"


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://si:si@localhost:5432/store_intelligence")
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        total = (await conn.execute(text("SELECT COUNT(*) FROM events WHERE store_id = :s"), {"s": STORE})).scalar()
        by_type = (await conn.execute(text(
            "SELECT event_type, COUNT(*) FROM events WHERE store_id = :s GROUP BY 1 ORDER BY 2 DESC"
        ), {"s": STORE})).all()
        by_cam = (await conn.execute(text(
            "SELECT payload->>'camera_id', COUNT(*) FROM events WHERE store_id = :s "
            "AND payload->>'camera_id' IS NOT NULL GROUP BY 1"
        ), {"s": STORE})).all()
        entries = (await conn.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s AND payload->>'is_store_entry' IN ('true','True','1')"
        ), {"s": STORE})).scalar()
        exits = (await conn.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s AND payload->>'is_store_exit' IN ('true','True','1')"
        ), {"s": STORE})).scalar()
        frames = (await conn.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s AND event_type = 'vision.frame.processed'"
        ), {"s": STORE})).scalar()
        sessions = (await conn.execute(text(
            "SELECT COUNT(*) FROM sessions WHERE store_id = :s"
        ), {"s": STORE})).scalar()
        print(f"total_events={total} frames={frames} sessions={sessions} entries={entries} exits={exits}")
        print("by_type:", dict(by_type))
        print("by_cam:", dict(by_cam))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
