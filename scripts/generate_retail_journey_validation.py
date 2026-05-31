#!/usr/bin/env python3
"""
Validate linked retail journeys: Visitor → Zone Visit → Billing Queue → Purchase.

Runs POS ingest, journey linking, API queries, and writes docs/RETAIL_JOURNEY_VALIDATION.md
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")
POS_CSV = REPO_ROOT / "data" / "pos" / "Brigade_Bangalore_10_April_26.csv"
PERIOD_START = datetime(2026, 4, 10, 0, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


async def _fetch_api_data() -> dict:
    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton
    from app.repositories.event_repository import EventRepository
    from app.repositories.funnel_repository import FunnelRepository
    from app.repositories.store_repository import StoreRepository
    from app.services.funnel_service import FunnelService

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
    async with sf() as session:
        svc = FunnelService(
            FunnelRepository(session),
            StoreRepository(session),
            EventRepository(session),
        )
        funnel = await svc.get_funnel(DEMO_STORE_ID, from_ts=PERIOD_START, to_ts=PERIOD_END)
        journeys = await svc.get_retail_journeys(
            DEMO_STORE_ID, from_ts=PERIOD_START, to_ts=PERIOD_END
        )
        complete = await svc.get_retail_journeys(
            DEMO_STORE_ID,
            from_ts=PERIOD_START,
            to_ts=PERIOD_END,
            complete_only=True,
        )
    await dispose_engine()

    stages = {s.stage: s for s in funnel.stages}
    return {
        "funnel": funnel,
        "stages": stages,
        "journeys": journeys,
        "complete_journeys": complete.journeys,
        "linked_meta": journeys.meta,
        "funnel_meta": funnel.meta,
    }


def _write_report(data: dict, link_stats: dict, ingest_stats: dict) -> Path:
    funnel = data["funnel"]
    stages = data["stages"]
    journeys = data["journeys"]
    complete = data["complete_journeys"]
    meta = data["linked_meta"]

    lines = [
        "# Retail Journey Validation",
        "",
        f"**Generated:** {datetime.now(tz=UTC).isoformat()}",
        f"**Store:** Brigade_Bangalore (`{DEMO_STORE_ID}`)",
        f"**POS source:** `Brigade_Bangalore_10_April_26.csv`",
        f"**Analysis period:** {PERIOD_START.date()} → {PERIOD_END.date()}",
        "",
        "## Journey model",
        "",
        "```",
        "  Visitor (CCTV track)  →  Zone Visit  →  Billing Queue  →  Purchase (POS)",
        "```",
        "",
        "Each stage is sourced from real ingested data:",
        "",
        "| Stage | Source | Signal |",
        "|-------|--------|--------|",
        "| **Visitor** | CCTV pipeline | `external_track_id` on vision events / sessions |",
        "| **Zone Visit** | CCTV pipeline | `vision.zone.entered` (browse, aisle, consultation, …) |",
        "| **Billing Queue** | CCTV pipeline | `vision.zone.entered` (`billing_queue`, `checkout`) |",
        "| **Purchase** | POS CSV | `transactions` row (NMV, invoice_number) linked to track |",
        "",
        "## Integration steps executed",
        "",
        "```bash",
        "python scripts/ingest_pos_csv.py --replace",
        "python scripts/link_pos_journeys.py --clear --mode auto",
        "python scripts/generate_retail_journey_validation.py",
        "```",
        "",
        "### POS ingest",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Orders parsed | {ingest_stats.get('orders', '—')} |",
        f"| Transactions inserted | {ingest_stats.get('inserted', '—')} |",
        f"| Revenue (NMV) | ₹{ingest_stats.get('revenue_nmv', '—')} |",
        "",
        "### Journey linking",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Billing-queue tracks | {link_stats.get('billing_tracks', 0)} |",
        f"| POS orders matched | {link_stats.get('linked', 0)} |",
        "",
        "| Track (suffix) | Invoice | Method | Confidence |",
        "|----------------|---------|--------|------------|",
    ]

    for match in link_stats.get("matches", []):
        lines.append(
            f"| …{match['track_id']} | `{match['invoice']}` | {match['method']} | {match['confidence']} |"
        )

    lines.extend([
        "",
        "## Funnel proof (API)",
        "",
        f"**Endpoint:** `GET /api/v1/stores/{DEMO_STORE_ID}/funnel`",
        "",
        "| Stage | Count | Sequential conversion |",
        "|-------|------:|--------------------:|",
    ])

    for name in ("ENTRY", "ZONE_VISIT", "BILLING_QUEUE", "PURCHASE"):
        s = stages[name]
        conv = f"{s.conversion_rate:.2%}" if s.conversion_rate is not None else "—"
        lines.append(f"| {name} | {s.count} | {conv} |")

    billing_conv = meta.get("billing_to_purchase_rate")
    lines.extend([
        "",
        "### Journey linkage metrics (funnel meta)",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Linked POS purchases | **{meta.get('linked_purchases', 0)}** |",
        f"| Complete 4-stage journeys | **{meta.get('complete_journeys', 0)}** |",
        f"| Billing → Purchase (linked tracks) | **{billing_conv:.1%}** |" if billing_conv else "",
        f"| Orphan POS (no track link) | {meta.get('pos_orphan_purchases', 0)} |",
        "",
        "## Linked journeys (sample)",
        "",
        f"**Endpoint:** `GET /api/v1/stores/{DEMO_STORE_ID}/funnel/journeys`",
        "",
        f"Total journeys: **{len(journeys.journeys)}** · Complete: **{len(complete)}**",
        "",
        "| Status | Track | Stages | Invoice | NMV (₹) | Link |",
        "|--------|-------|--------|---------|--------:|------|",
    ])

    for j in complete[:8]:
        stage_path = " → ".join(s.stage for s in j.stages)
        inv = j.purchase.invoice_number if j.purchase else "—"
        amt = f"{j.purchase.amount:,.2f}" if j.purchase else "—"
        method = j.purchase.link_method if j.purchase else "—"
        track = (j.external_track_id or "")[-12:]
        lines.append(f"| ✅ Complete | …{track} | {stage_path} | `{inv}` | {amt} | {method} |")

    lines.extend([
        "",
        "## Dashboard proof",
        "",
        f"- **URL:** http://localhost:8000/dashboard/",
        "- **Section:** *Linked retail journeys* (Visitor → Zone → Billing → Purchase table)",
        "- **Badges:** Linked POS receipts · Complete journeys · Billing→Purchase rate",
        "",
        "## API verification",
        "",
        "```bash",
        'curl -s -H "X-API-Key: purple-demo-key" \\',
        f'  "http://localhost:8000/api/v1/stores/{DEMO_STORE_ID}/funnel/journeys" | jq ".meta, .journeys[:3]"',
        "",
        'curl -s -H "X-API-Key: purple-demo-key" \\',
        f'  "http://localhost:8000/api/v1/stores/{DEMO_STORE_ID}/funnel" | jq ".meta.linked_purchases, .stages"',
        "```",
        "",
        "## Data alignment notes",
        "",
        "- POS billing timestamps are **10-Apr-2026** store-local (parsed as UTC).",
        "- CCTV vision events use **pipeline ingest timestamps** (~May 2026 reprocessing).",
        "- When absolute timestamps do not overlap, linking uses **sequential fallback**:",
        "  billing-queue tracks (ordered by queue entry) ↔ POS orders (ordered by billing time).",
        "- Link metadata stored on each transaction: `metadata.journey_link.method`, `confidence`.",
        "",
        "---",
        "",
        f"*Linked purchases: {meta.get('linked_purchases', 0)} · "
        f"Complete journeys: {meta.get('complete_journeys', 0)} · "
        f"Funnel PURCHASE count: {stages['PURCHASE'].count}*",
    ])

    out = REPO_ROOT / "docs" / "RETAIL_JOURNEY_VALIDATION.md"
    out.write_text("\n".join(line for line in lines if line is not None) + "\n", encoding="utf-8")
    return out


async def main() -> int:
    if not POS_CSV.is_file():
        print(f"ERROR: {POS_CSV} not found")
        return 1

    ingest = _run([sys.executable, "scripts/ingest_pos_csv.py", "--replace"])
    print(ingest.stdout.strip())

    link = _run([sys.executable, "scripts/link_pos_journeys.py", "--clear", "--mode", "auto"])
    print(link.stdout.strip())

    link_stats = {}
    for line in link.stdout.splitlines():
        if line.startswith("Linked:"):
            link_stats["linked"] = int(line.split(":")[1].strip())
        if line.startswith("Billing tracks:"):
            link_stats["billing_tracks"] = int(line.split(":")[1].strip())
    link_stats["matches"] = []
    for line in link.stdout.splitlines():
        if line.strip().startswith("track"):
            parts = line.strip().split()
            link_stats["matches"].append(
                {
                    "track_id": parts[1].replace("…", ""),
                    "invoice": parts[3],
                    "method": parts[4].strip("(),"),
                    "confidence": parts[5].replace("conf=", "").strip(")"),
                }
            )

    ingest_stats = {}
    for line in ingest.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            ingest_stats[k.strip().lower().replace(" ", "_")] = v.strip()

    data = await _fetch_api_data()
    report = _write_report(data, link_stats, ingest_stats)

    json_out = REPO_ROOT / "docs" / "evidence" / "retail_journey_validation.json"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "link_stats": link_stats,
                "funnel_meta": data["funnel_meta"],
                "journey_meta": data["linked_meta"],
                "complete_journey_count": len(data["complete_journeys"]),
                "purchase_stage_count": data["stages"]["PURCHASE"].count,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {report}")
    print(f"Wrote {json_out}")
    print(
        f"Complete journeys: {data['linked_meta'].get('complete_journeys')} · "
        f"Linked purchases: {data['linked_meta'].get('linked_purchases')} · "
        f"PURCHASE stage: {data['stages']['PURCHASE'].count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
