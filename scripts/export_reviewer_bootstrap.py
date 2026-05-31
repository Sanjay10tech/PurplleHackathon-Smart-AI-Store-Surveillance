#!/usr/bin/env python3
"""Export YOLO vision events to committed reviewer bootstrap JSONL."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_STORE = UUID("00000000-0000-0000-0000-000000000101")
DEFAULT_OUT = REPO_ROOT / "data" / "reviewer" / "yolo_bootstrap_events.jsonl"
VISION_TYPES = {
    "vision.frame.processed",
    "vision.zone.entered",
    "vision.zone.exited",
    "vision.track.started",
    "vision.track.ended",
    "vision.session.started",
    "vision.session.ended",
}


def _event_to_ingest(row) -> dict:
    payload = dict(row.payload or {})
    payload.setdefault("detector_mode", "yolo")
    source = payload.get("source_video")
    if source:
        payload["source_video"] = Path(str(source)).name
    return {
        "event_id": str(row.id),
        "event_type": row.event_type,
        "schema_version": row.schema_version,
        "tenant_id": str(row.tenant_id),
        "store_id": str(row.store_id),
        "occurred_at": row.occurred_at.isoformat().replace("+00:00", "Z"),
        "correlation_id": row.correlation_id,
        "idempotency_key": row.idempotency_key,
        "aggregate": {
            "type": row.aggregate_type,
            "id": str(row.aggregate_id),
        },
        "payload": payload,
    }


async def export_events(store_id: UUID, output: Path, *, yolo_only: bool) -> int:
    from sqlalchemy import select

    from app.database import create_engine, create_session_factory, dispose_engine
    from app.models import Event

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = url

    output.parent.mkdir(parents=True, exist_ok=True)
    session_factory = create_session_factory(create_engine())
    count = 0

    async with session_factory() as session:
        result = await session.execute(
            select(Event)
            .where(
                Event.store_id == store_id,
                Event.event_type.in_(VISION_TYPES),
            )
            .order_by(Event.occurred_at)
        )
        rows = list(result.scalars())
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                mode = (row.payload or {}).get("detector_mode")
                if yolo_only and mode == "mock":
                    continue
                handle.write(json.dumps(_event_to_ingest(row), separators=(",", ":")))
                handle.write("\n")
                count += 1

    await dispose_engine()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Export reviewer CCTV bootstrap JSONL")
    parser.add_argument("--store-id", type=UUID, default=DEFAULT_STORE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--include-mock",
        action="store_true",
        help="Include mock detector events (default: YOLO only)",
    )
    args = parser.parse_args()
    count = asyncio.run(export_events(args.store_id, args.output, yolo_only=not args.include_mock))
    print(f"Exported {count} events -> {args.output}")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
