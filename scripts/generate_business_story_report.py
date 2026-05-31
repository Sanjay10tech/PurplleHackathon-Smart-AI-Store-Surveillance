#!/usr/bin/env python3
"""Generate BUSINESS_STORY_REPORT.md from live funnel + journey data."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT_PATH = REPO_ROOT / "BUSINESS_STORY_REPORT.md"
EVIDENCE_JSON = REPO_ROOT / "docs" / "evidence" / "business_story.json"
DEFAULT_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")


async def _fetch_funnel_data(
    store_id: UUID,
    *,
    from_ts: datetime | None,
    to_ts: datetime | None,
) -> dict:
    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton
    from app.domain.funnel.stages import (
        FUNNEL_STAGE_ORDER,
        STAGE_BUSINESS_LABELS,
        business_story_meta,
    )
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
        funnel = await svc.get_funnel(store_id, from_ts=from_ts, to_ts=to_ts)
        journeys = await svc.get_retail_journeys(store_id, from_ts=from_ts, to_ts=to_ts)
        complete = await svc.get_retail_journeys(
            store_id, from_ts=from_ts, to_ts=to_ts, complete_only=True
        )

    await dispose_engine()

    stages = {s.stage: s for s in funnel.stages}
    story_meta = business_story_meta()
    return {
        "store_id": str(store_id),
        "period_start": funnel.period_start.isoformat(),
        "period_end": funnel.period_end.isoformat(),
        "unique_visitors": funnel.unique_visitors,
        "stages": stages,
        "stage_order": [s.value for s in FUNNEL_STAGE_ORDER],
        "stage_labels": {s.value: STAGE_BUSINESS_LABELS[s] for s in FUNNEL_STAGE_ORDER},
        "meta": funnel.meta,
        "journeys_total": len(journeys.journeys),
        "journeys_complete": len(complete.journeys),
        "journey_meta": journeys.meta,
        "sample_journeys": complete.journeys[:5],
        "story_meta": story_meta,
    }


def _write_report(data: dict) -> None:
    stages = data["stages"]
    meta = data["meta"]
    jmeta = data["journey_meta"]
    labels = data["stage_labels"]

    lines = [
        "# Business Story Report",
        "",
        f"**Generated:** {datetime.now(tz=UTC).isoformat()}  ",
        f"**Store:** `{data['store_id']}`  ",
        f"**Period:** {data['period_start']} → {data['period_end']}",
        "",
        "## Executive summary",
        "",
        "Store Intelligence connects **CCTV vision events** and **POS transactions** into one",
        "retail funnel. Each shopper progresses through four business stages:",
        "",
        "```",
        "  Visitor  →  Zone Visit  →  Billing Queue  →  Purchase",
        "  (CCTV)      (CCTV)          (CCTV)            (POS)",
        "```",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Unique visitors (tracks) | **{data['unique_visitors']}** |",
        f"| Customer sessions | **{meta.get('session_count', '—')}** |",
        f"| Linked POS purchases | **{jmeta.get('linked_purchases', meta.get('linked_purchases', 0))}** |",
        f"| Complete 4-stage journeys | **{data['journeys_complete']}** |",
        "",
        "---",
        "",
        "## 1. Stage definitions",
        "",
        "| Business step | Engine stage | Source | How it is detected |",
        "|---------------|--------------|--------|--------------------|",
    ]

    for step in data["story_meta"]["business_story"]:
        lines.append(
            f"| **{step['label']}** | `{step['stage']}` | {step['source']} | {step['signal']} |"
        )

    lines.extend([
        "",
        "Staff tracks and `staff_only` zones are excluded from customer funnel metrics.",
        "",
        "---",
        "",
        "## 2. Funnel counts (live data)",
        "",
        "| Business step | Stage | Count | Re-entries | Conversion to next | Drop-off |",
        "|---------------|-------|------:|-----------:|-------------------:|---------:|",
    ])

    for stage_key in data["stage_order"]:
        s = stages[stage_key]
        label = labels[stage_key]
        conv = f"{s.conversion_rate:.1%}" if s.conversion_rate is not None else "—"
        drop = f"{s.drop_off_rate:.1%}" if s.drop_off_rate is not None else "—"
        lines.append(
            f"| {label} | `{stage_key}` | **{s.count}** | {s.re_entry_count} | {conv} | {drop} |"
        )

    entry = stages.get("ENTRY")
    purchase = stages.get("PURCHASE")
    e2e = "—"
    if entry and purchase and entry.count > 0:
        e2e = f"{min(1.0, purchase.count / entry.count):.1%}"

    lines.extend([
        "",
        "---",
        "",
        "## 3. How conversion is calculated",
        "",
        "### Sequential stage conversion",
        "",
        data["story_meta"]["conversion_formula"],
        "",
        "**Worked example (from current data):**",
        "",
    ])

    for i, stage_key in enumerate(data["stage_order"][:-1]):
        s = stages[stage_key]
        next_key = data["stage_order"][i + 1]
        next_label = labels[next_key]
        if s.conversion_rate is not None and s.count > 0:
            reached_both = round(s.conversion_rate * s.count)
            lines.append(
                f"- **{labels[stage_key]} → {next_label}:** "
                f"{reached_both} of {s.count} visitors = **{s.conversion_rate:.1%}** conversion, "
                f"**{s.drop_off_rate:.1%}** drop-off"
            )

    lines.extend([
        "",
        "### End-to-end purchase conversion",
        "",
        data["story_meta"]["end_to_end_conversion_formula"],
        "",
        f"**Current Visitor → Purchase rate:** **{e2e}** "
        f"(`PURCHASE.count={purchase.count if purchase else 0}` / "
        f"`ENTRY.count={entry.count if entry else 0}`, capped at 100%)",
        "",
        "### Re-entries",
        "",
        "When a visitor re-enters the same stage after the first touch, `re_entry_count` "
        "increments but the stage `count` does not — the funnel measures **first-touch** progression.",
        "",
        "---",
        "",
        "## 4. Linked retail journeys",
        "",
        f"**Endpoint:** `GET /api/v1/stores/{data['store_id']}/funnel/journeys`",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Total journey rows | **{data['journeys_total']}** |",
        f"| Complete journeys (all 4 stages + POS) | **{data['journeys_complete']}** |",
        (
            f"| Billing → Purchase (linked tracks) | **{jmeta['billing_to_purchase_rate']:.1%}** |"
            if jmeta.get("billing_to_purchase_rate") is not None
            else "| Billing → Purchase (linked tracks) | — |"
        ),
        "",
    ])

    samples = data["sample_journeys"]
    if samples:
        lines.extend([
            "### Sample complete journeys",
            "",
            "| Track (suffix) | Path | Invoice | Amount (₹) |",
            "|----------------|------|---------|----------:|",
        ])
        for j in samples:
            path = " → ".join(labels.get(s.stage, s.stage) for s in j.stages)
            inv = j.purchase.invoice_number if j.purchase else "—"
            amt = f"{j.purchase.amount:,.2f}" if j.purchase else "—"
            track = (j.external_track_id or "")[-12:]
            lines.append(f"| …{track} | {path} | `{inv}` | {amt} |")
    else:
        lines.append(
            "_No complete journeys in period. Run `python scripts/link_pos_journeys.py` after POS ingest._"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 5. Dashboard & API",
        "",
        "| Surface | Location |",
        "|---------|----------|",
        "| Live dashboard | http://localhost:8000/dashboard/ → **Business story** |",
        "| Funnel API | `GET /api/v1/stores/{id}/funnel` |",
        "| Journeys API | `GET /api/v1/stores/{id}/funnel/journeys` |",
        "| Domain logic | `app/domain/funnel/calculator.py` |",
        "",
        "---",
        "",
        "## 6. Reproduce",
        "",
        "```bash",
        "docker compose up -d",
        "python scripts/setup_videos.py --check",
        "python -m pipeline.run --ingest --persist-sessions --camera \"CAM 3\" --max-frames 25",
        "python scripts/ingest_pos_csv.py --replace   # optional POS",
        "python scripts/link_pos_journeys.py --clear --mode auto",
        "python scripts/generate_business_story_report.py",
        "```",
        "",
    ])

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    bundle = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        **data,
        "stages": {
            k: {
                "count": v.count,
                "conversion_rate": v.conversion_rate,
                "drop_off_rate": v.drop_off_rate,
                "re_entry_count": v.re_entry_count,
            }
            for k, v in data["stages"].items()
        },
    }
    EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_JSON.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Generate BUSINESS_STORY_REPORT.md")
    parser.add_argument("--store-id", default=str(DEFAULT_STORE_ID))
    parser.add_argument("--hours", type=int, default=720, help="Lookback window (default 30 days)")
    args = parser.parse_args()

    store_id = UUID(args.store_id)
    to_ts = datetime.now(tz=UTC)
    from_ts = to_ts - timedelta(hours=args.hours)

    print(f"Fetching funnel data for store {store_id}...")
    data = await _fetch_funnel_data(store_id, from_ts=from_ts, to_ts=to_ts)
    _write_report(data)
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {EVIDENCE_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
