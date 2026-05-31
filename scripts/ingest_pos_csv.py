#!/usr/bin/env python3
"""Ingest Purplle POS CSV into transactions + PURCHASE events (uses PosIngestionService)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CSV = REPO_ROOT / "data" / "pos" / "Brigade_Bangalore_10_April_26.csv"
DEMO_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")


async def main_async(args: argparse.Namespace) -> int:
    import os

    from app.config import get_settings
    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton
    from app.services.pos_ingestion_service import PosIngestionService

    if not args.csv.is_file():
        print(f"WARNING: CSV not found: {args.csv}")
        return 0

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = url
    reset_engine_singleton()

    settings = get_settings()
    engine = create_engine()
    sf = create_session_factory(engine)

    async with sf() as session:
        service = PosIngestionService(session, settings)
        if args.dry_run:
            from app.domain.pos.csv_parser import parse_pos_csv

            orders, analysis = parse_pos_csv(args.csv)
            print(f"Orders parsed: {len(orders)}")
            print(f"CSV lines: {analysis.line_count}")
            print(f"Columns: {len(analysis.all_columns)}")
            print(f"Revenue (NMV): {sum(o.nmv for o in orders)} INR")
            await dispose_engine()
            return 0

        result = await service.ingest_store_pos(
            args.store_id,
            csv_path=args.csv,
            replace_existing=args.replace,
            link_journeys=not args.no_link,
            emit_purchase_events=not args.no_events,
        )

    await dispose_engine()

    if result.errors:
        for err in result.errors:
            print(f"ERROR: {err}")
        return 1

    print(f"Orders parsed: {result.orders_parsed}")
    print(f"Transactions inserted: {result.transactions_inserted}")
    print(f"Transactions skipped: {result.transactions_skipped}")
    print(f"CCTV sessions linked: {result.sessions_linked}")
    print(f"PURCHASE events created: {result.purchase_events_created}")
    print(f"Revenue (NMV): {result.revenue_nmv} INR")
    if result.aggregates and result.aggregates.top_brands:
        print("Top brands:")
        for b in result.aggregates.top_brands:
            print(f"  {b.name}: INR {b.revenue}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Brigade Road POS CSV")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--store-id", type=UUID, default=DEMO_STORE_ID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--no-link", action="store_true", help="Skip CCTV correlation")
    parser.add_argument("--no-events", action="store_true", help="Skip PURCHASE event emission")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
