#!/usr/bin/env python3
"""Conversion funnel audit — raw SQL vs funnel engine vs dashboard API."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")

ENTRY_ZONES = ("entry_threshold", "entrance", "entry")
ZONE_VISIT_ZONES = (
    "aisle",
    "promo_island",
    "consultation",
    "browse",
    "browse_skincare",
    "browse_cosmetics",
    "display",
    "zone",
)
BILLING_ZONES = ("billing_queue", "checkout", "queue", "billing")

# Pre-fix dashboard snapshot (session-gated funnel, missing zone mappings)
BEFORE_DASHBOARD = {
    "unique_visitors": 22,
    "ENTRY": 1,
    "ZONE_VISIT": 0,
    "BILLING_QUEUE": 0,
    "PURCHASE": 0,
}


@dataclass
class StageAudit:
    stage: str
    raw_events: int
    distinct_tracks: int
    aggregated: int
    dashboard: int

    @property
    def pass_match(self) -> bool:
        return self.distinct_tracks == self.aggregated == self.dashboard


async def _sql_counts(session_factory) -> tuple[dict, list[StageAudit], dict]:
    from sqlalchemy import text

    store = str(DEMO_STORE_ID)
    async with session_factory() as session:
        by_type = await session.execute(
            text(
                """
                SELECT event_type,
                       COUNT(*) AS event_count,
                       COUNT(DISTINCT payload->>'external_track_id')
                         FILTER (WHERE payload->>'external_track_id' IS NOT NULL
                                   AND payload->>'external_track_id' != '') AS distinct_tracks
                FROM events WHERE store_id = :store
                GROUP BY event_type ORDER BY event_count DESC
                """
            ),
            {"store": store},
        )
        event_types = [dict(r._mapping) for r in by_type]

        stage_rows = await session.execute(
            text(
                """
                WITH customer_zones AS (
                  SELECT payload->>'external_track_id' AS track_id,
                         payload->>'zone_type' AS zone_type
                  FROM events
                  WHERE store_id = :store
                    AND event_type = 'vision.zone.entered'
                    AND COALESCE(payload->>'class_label','') != 'staff'
                    AND COALESCE(payload->>'zone_type','') NOT IN ('staff_only','ignore')
                    AND payload->>'external_track_id' IS NOT NULL
                    AND payload->>'external_track_id' != ''
                )
                SELECT 'ENTRY' AS stage, COUNT(*) AS raw_events,
                       COUNT(DISTINCT track_id) AS distinct_tracks
                FROM customer_zones WHERE zone_type = ANY(:entry_zones)
                UNION ALL
                SELECT 'ZONE_VISIT', COUNT(*), COUNT(DISTINCT track_id)
                FROM customer_zones WHERE zone_type = ANY(:zone_visit_zones)
                UNION ALL
                SELECT 'BILLING_QUEUE', COUNT(*), COUNT(DISTINCT track_id)
                FROM customer_zones WHERE zone_type = ANY(:billing_zones)
                UNION ALL
                SELECT 'PURCHASE', 0, COUNT(*)::bigint
                FROM transactions WHERE store_id = :store AND status = 'completed'
                """
            ),
            {
                "store": store,
                "entry_zones": list(ENTRY_ZONES),
                "zone_visit_zones": list(ZONE_VISIT_ZONES),
                "billing_zones": list(BILLING_ZONES),
            },
        )
        raw_stages = {r.stage: (r.raw_events, r.distinct_tracks) for r in stage_rows}

        from app.repositories.event_repository import EventRepository
        from app.repositories.funnel_repository import FunnelRepository
        from app.repositories.store_repository import StoreRepository
        from app.services.funnel_service import FunnelService
        from datetime import UTC, datetime, timedelta

        service = FunnelService(
            funnel_repository=FunnelRepository(session),
            store_repository=StoreRepository(session),
            event_repository=EventRepository(session),
        )
        now = datetime.now(tz=UTC)
        funnel = await service.get_funnel(DEMO_STORE_ID, from_ts=now - timedelta(hours=24), to_ts=now)
        aggregated = {s.stage: s.count for s in funnel.stages}

        stages = []
        for name in ("ENTRY", "ZONE_VISIT", "BILLING_QUEUE", "PURCHASE"):
            raw, distinct = raw_stages[name]
            stages.append(
                StageAudit(
                    stage=name,
                    raw_events=int(raw),
                    distinct_tracks=int(distinct),
                    aggregated=aggregated.get(name, 0),
                    dashboard=0,
                )
            )

        summary = {
            "unique_visitors_sql": int(
                (
                    await session.execute(
                        text(
                            """
                            SELECT COUNT(DISTINCT payload->>'external_track_id')
                            FROM events WHERE store_id = :store
                              AND payload->>'external_track_id' IS NOT NULL
                              AND payload->>'external_track_id' != ''
                            """
                        ),
                        {"store": store},
                    )
                ).scalar_one()
            ),
            "unique_visitors_aggregated": funnel.unique_visitors,
            "total_events": int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM events WHERE store_id = :store"),
                        {"store": store},
                    )
                ).scalar_one()
            ),
            "sessions": int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM sessions WHERE store_id = :store"),
                        {"store": store},
                    )
                ).scalar_one()
            ),
        }
    return event_types, stages, summary


def _fetch_dashboard_funnel() -> dict:
    base = os.environ.get("API_BASE", "http://localhost:8000")
    key = os.environ.get("API_KEY", "purple-demo-key")
    req = urllib.request.Request(
        f"{base}/api/v1/stores/{DEMO_STORE_ID}/funnel",
        headers={"X-API-Key": key},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _count_jsonl_events() -> int | None:
    path = REPO_ROOT / "data" / "pipeline" / "events.jsonl"
    if not path.exists():
        return None
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


async def main() -> int:
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
    session_factory = create_session_factory(engine)

    event_types, stages, summary = await _sql_counts(session_factory)
    await dispose_engine()

    try:
        api = _fetch_dashboard_funnel()
        dash_stages = {s["stage"]: s["count"] for s in api["stages"]}
        dash_uv = api["unique_visitors"]
    except Exception as exc:
        print(f"WARN: could not reach dashboard API: {exc}")
        dash_stages = {}
        dash_uv = -1

    for stage in stages:
        stage.dashboard = dash_stages.get(stage.stage, -1)

    jsonl_count = _count_jsonl_events()
    all_pass = all(s.pass_match for s in stages) and summary["unique_visitors_aggregated"] == dash_uv

    print("=" * 72)
    print("CONVERSION FUNNEL AUDIT")
    print("=" * 72)
    print(f"\nStore: {DEMO_STORE_ID}")
    print(f"DB events ingested: {summary['total_events']}")
    if jsonl_count is not None:
        print(f"Pipeline JSONL events generated: {jsonl_count}")
    print(f"Unique visitors (SQL): {summary['unique_visitors_sql']}")
    print(f"Sessions: {summary['sessions']}")

    print("\n--- 1. Raw counts by event_type ---")
    for row in event_types:
        print(
            f"  {row['event_type']:30} events={row['event_count']:4}  "
            f"distinct_tracks={row['distinct_tracks'] or 0}"
        )

    print("\n--- 2-5. Funnel stages: raw events | distinct tracks | aggregated | dashboard ---")
    for s in stages:
        status = "OK" if s.pass_match else "MISMATCH"
        print(
            f"  {s.stage:14} raw={s.raw_events:4}  expected={s.distinct_tracks:3}  "
            f"aggregated={s.aggregated:3}  dashboard={s.dashboard:3}  [{status}]"
        )

    after = {s.stage: s.dashboard for s in stages}
    after["unique_visitors"] = dash_uv

    print("\n" + "=" * 72)
    print("BEFORE (broken session-gated funnel)")
    print(json.dumps(BEFORE_DASHBOARD, indent=2))
    print("\nAFTER (current)")
    print(json.dumps(after, indent=2))
    print(f"\n{'PASS' if all_pass else 'FAIL'}")
    print("=" * 72)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
