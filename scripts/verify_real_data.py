import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

STORE = "00000000-0000-0000-0000-000000000101"

async def main():
    e = create_async_engine("postgresql+asyncpg://si:si@localhost:5432/store_intelligence")
    async with e.connect() as c:
        tx = (await c.execute(text(
            "SELECT COUNT(*) AS n, SUM(amount) AS rev, "
            "MIN(metadata->>'source') AS src "
            "FROM transactions WHERE store_id = :s"
        ), {"s": STORE})).one()
        pe = (await c.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s "
            "AND event_type = 'analytics.purchase.completed'"
        ), {"s": STORE})).scalar()
        ve = (await c.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s AND event_type LIKE 'vision.%'"
        ), {"s": STORE})).scalar()
        linked = (await c.execute(text(
            "SELECT COUNT(*) FROM transactions WHERE store_id = :s "
            "AND metadata->>'external_track_id' IS NOT NULL"
        ), {"s": STORE})).scalar()
        mock = (await c.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s "
            "AND payload->>'detector_mode' = 'mock'"
        ), {"s": STORE})).scalar()
        yolo = (await c.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s "
            "AND payload->>'detector_mode' = 'yolo'"
        ), {"s": STORE})).scalar()
        frames = (await c.execute(text(
            "SELECT COUNT(*) FROM events WHERE store_id = :s "
            "AND event_type = 'vision.frame.processed'"
        ), {"s": STORE})).scalar()
        print(f"transactions={tx.n} revenue={tx.rev} source={tx.src}")
        print(f"purchase_events={pe} vision_events={ve} frames={frames}")
        print(f"linked_transactions={linked} mock={mock} yolo={yolo}")
    await e.dispose()

asyncio.run(main())
