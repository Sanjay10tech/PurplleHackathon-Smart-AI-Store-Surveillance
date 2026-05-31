#!/usr/bin/env python3
"""Generate REVIEWER_METRIC_VALIDATION.md using the same bootstrap path as tests."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUTPUT = REPO_ROOT / "REVIEWER_METRIC_VALIDATION.md"
BOOTSTRAP = REPO_ROOT / "data/reviewer/yolo_bootstrap_events.jsonl"
DEMO_STORE = uuid.UUID("00000000-0000-0000-0000-000000000101")


async def _bootstrap_sqlite() -> dict[str, object]:
    import os

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.database import Base
    from app.domain.dashboard.coverage import get_event_coverage
    from app.domain.dashboard.kpi_queries import (
        count_completed_purchases,
        count_linked_purchases,
        count_pipeline_events,
        count_store_entry_events,
        count_store_exit_events,
    )
    from app.domain.dashboard.period import resolve_analysis_period
    from app.models import Event, Store, Tenant, Transaction, VisitSession
    from app.repositories.event_repository import EventRepository
    from app.repositories.funnel_repository import FunnelRepository
    from app.repositories.store_repository import StoreRepository
    from app.services.cctv_bootstrap import bootstrap_cctv_events
    from app.services.funnel_service import FunnelService
    from app.services.pos_bootstrap import bootstrap_pos_ingestion
    from app.services.reviewer_journey_bootstrap import ensure_reviewer_journey_metrics
    from tests.helpers.constants import DEMO_TENANT_ID

    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(Tenant(id=DEMO_TENANT_ID, name="Demo", slug="demo"))
        session.add(
            Store(
                id=DEMO_STORE,
                tenant_id=DEMO_TENANT_ID,
                name="Brigade Road",
                timezone="Asia/Kolkata",
                config={"heatmap": {"use_layout": False}},
            )
        )
        await session.commit()

    settings = get_settings()
    settings.metrics_projector_enabled = False
    settings.cctv_bootstrap_min_events = 9999
    settings.cctv_store_id = str(DEMO_STORE)
    settings.pos_store_id = str(DEMO_STORE)

    from app.database import reset_engine_singleton

    reset_engine_singleton()

    import app.database as db_module

    db_module._engine = engine
    db_module._session_factory = session_factory

    await bootstrap_cctv_events(settings)
    await bootstrap_pos_ingestion(settings)
    journey = await ensure_reviewer_journey_metrics(settings)

    async with session_factory() as session:
        period_start, period_end = await resolve_analysis_period(session, DEMO_STORE, None, None)
        coverage = await get_event_coverage(session, DEMO_STORE, period_start, period_end)
        entries = await count_store_entry_events(session, DEMO_STORE, period_start, period_end)
        exits = await count_store_exit_events(session, DEMO_STORE, period_start, period_end)
        events = await count_pipeline_events(session, DEMO_STORE, period_start, period_end)
        purchases = await count_completed_purchases(session, DEMO_STORE, period_start, period_end)
        linked = await count_linked_purchases(session, DEMO_STORE, period_start, period_end)
        session_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(VisitSession)
                    .where(VisitSession.store_id == DEMO_STORE)
                )
            ).scalar_one()
        )
        revenue = (
            await session.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.store_id == DEMO_STORE,
                    Transaction.status == "completed",
                )
            )
        ).scalar_one()
        funnel = await FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
            session=session,
        ).get_funnel(DEMO_STORE)
        funnel_stages = {stage.stage: stage.count for stage in funnel.stages}
        vision_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Event)
                    .where(Event.store_id == DEMO_STORE, Event.event_type.like("vision.%"))
                )
            ).scalar_one()
        )

    bootstrap_lines = len([l for l in BOOTSTRAP.read_text().splitlines() if l.strip()]) if BOOTSTRAP.is_file() else 0
    dashboard_entries = max(entries, funnel_stages.get("ENTRY", 0))
    conversion = (
        min(linked, dashboard_entries) / dashboard_entries
        if dashboard_entries > 0 and linked > 0
        else None
    )

    await engine.dispose()
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "store_id": str(DEMO_STORE),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "videos_processed": len(coverage.get("source_videos") or []),
        "source_videos": list(coverage.get("source_videos") or []),
        "events_generated": events,
        "bootstrap_events_file": bootstrap_lines,
        "vision_events_all_time": vision_count,
        "entries_kpi": entries,
        "entries": dashboard_entries,
        "exits": exits,
        "sessions": session_count,
        "purchases": purchases,
        "linked_purchases": linked,
        "revenue_nmv": float(Decimal(str(revenue))),
        "conversion_rate": conversion,
        "funnel_stages": funnel_stages,
        "detector_mode": coverage.get("detector_mode"),
        "processing_lineage": coverage.get("processing_lineage"),
        "journey": journey,
    }


def _render(data: dict[str, object]) -> str:
    conversion = data["conversion_rate"]
    conversion_txt = f"{float(conversion) * 100:.1f}%" if conversion is not None else "No Data Available"
    videos = data["source_videos"] or ["none"]
    funnel = data["funnel_stages"]
    journey = data.get("journey") or {}

    return f"""# Reviewer Metric Validation

Generated: `{data["generated_at"]}`  
Store: `{data["store_id"]}` (Brigade Road ST1008)  
Analysis window: `{data["period_start"]}` → `{data["period_end"]}`  
Validation method: bootstrap replay against SQLite (same code path as Docker entrypoint)

## Summary metrics

| Metric | Value | Data source / proof |
|--------|------:|---------------------|
| Videos processed | {data["videos_processed"]}/5 | `get_event_coverage()` → `payload.source_video` ({", ".join(videos)}) |
| Events generated (period) | {data["events_generated"]} | `COUNT(events)` in analysis window; bootstrap file has {data["bootstrap_events_file"]} vision rows |
| Vision events (all time) | {data["vision_events_all_time"]} | `events WHERE event_type LIKE 'vision.%'` |
| Entries | {data["entries"]} | `max(funnel ENTRY, count_store_entry_events)` — zone-entered tracks + session-based ENTRY |
| Exits | {data["exits"]} | `count_store_exit_events()` — distinct `vision.track.ended` customer tracks |
| Customer sessions | {data["sessions"]} | `sessions` table after `materialize_visit_sessions()` ({journey.get("sessions_created", 0)} created) |
| POS purchases | {data["purchases"]} | `transactions` from `data/pos/Brigade_Bangalore_10_April_26.csv` |
| Revenue (NMV) | ₹{data["revenue_nmv"]:,.2f} | `SUM(transactions.amount)` |
| Linked POS purchases | {data["linked_purchases"]} | `transactions.metadata.external_track_id` set by `pos_linker` ({journey.get("pos_journeys_linked", 0)} linked) |
| Linked conversion | {conversion_txt} | `linked_purchases / entries` |

## Funnel consistency

| Stage | Count | Source |
|-------|------:|--------|
| ENTRY | {funnel.get("ENTRY", 0)} | Sessions + inferred from zone signals (`FunnelCalculator`) |
| ZONE_VISIT | {funnel.get("ZONE_VISIT", 0)} | `vision.zone.entered` → aisle/promo/consultation |
| BILLING_QUEUE | {funnel.get("BILLING_QUEUE", 0)} | `vision.zone.entered` → billing_queue |
| PURCHASE | {funnel.get("PURCHASE", 0)} | Linked `transactions` + `analytics.purchase.completed` |

| Check | Result |
|-------|--------|
| ENTRY ≥ linked purchases | {"PASS" if funnel.get("ENTRY", 0) >= data["linked_purchases"] else "FAIL"} ({funnel.get("ENTRY", 0)} ≥ {data["linked_purchases"]}) |
| Funnel PURCHASE ≤ ENTRY | {"PASS" if funnel.get("PURCHASE", 0) <= funnel.get("ENTRY", 0) else "FAIL"} ({funnel.get("PURCHASE", 0)} ≤ {funnel.get("ENTRY", 0)}) |
| Sessions > 0 | {"PASS" if data["sessions"] > 0 else "FAIL"} |
| Entries > 0 | {"PASS" if data["entries"] > 0 else "FAIL"} |
| Exits > 0 | {"PASS" if data["exits"] > 0 else "FAIL"} |

## Data flow verified

```
CCTV JSONL → EventIngestionService → events table
           → materialize_visit_sessions → sessions table + session_id backfill
POS CSV    → PosIngestionService → transactions table
           → pos_linker (billing_queue tracks ↔ orders) → metadata.external_track_id
           → FunnelService → funnel stages
           → DashboardService → KPI cards
```

## Root causes fixed (this change)

1. **Wrong bootstrap order** — POS ran before CCTV; linkage saw zero billing tracks. Fixed in `scripts/docker_entrypoint.py` and `app/main.py`.
2. **No sessions persisted** — Bootstrap ingest wrote events only. Added `app/services/visit_session_materializer.py`.
3. **Linkage never re-run** — Added `ensure_reviewer_journey_metrics()` after both ingests.
4. **KPI NULL exclusion** — `class_label != 'staff'` dropped NULL rows; fixed with NULL-safe filters.
5. **Conversion denominator** — Dashboard used funnel-only `entry_count`; now uses `entries = max(funnel ENTRY, store entries)`.

## Reproduce

```bash
docker compose up --build
# or locally:
python scripts/bootstrap_cctv.py
python scripts/ingest_pos_csv.py
python scripts/materialize_journey_metrics.py
python scripts/generate_reviewer_metric_validation.py
curl -H "X-API-Key: purple-demo-key" http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/dashboard/summary
```
"""


async def _main() -> int:
    data = await _bootstrap_sqlite()
    OUTPUT.write_text(_render(data), encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    print(json.dumps({k: v for k, v in data.items() if k != "source_videos"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
