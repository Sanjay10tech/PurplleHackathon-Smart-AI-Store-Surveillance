#!/usr/bin/env python3
"""
Analyze Brigade_Bangalore POS CSV and integrate with CCTV funnel metrics.

Writes docs/POS_FUNNEL_INTEGRATION.md
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

POS_CSV = REPO_ROOT / "data" / "pos" / "Brigade_Bangalore_10_April_26.csv"
DEMO_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")
STORE_CODE = "ST1008"
CCTV_PILOT_START = datetime(2026, 4, 10, 20, 0, 0, tzinfo=UTC)
CCTV_PILOT_END = datetime(2026, 4, 10, 21, 45, 0, tzinfo=UTC)


@dataclass(frozen=True)
class PosOrder:
    order_id: str
    invoice_number: str
    occurred_at: datetime
    nmv: Decimal
    gmv: Decimal
    line_count: int
    customer_name: str


def _parse_dt(date_s: str, time_s: str) -> datetime:
    d, m, y = date_s.split("-")
    hh, mm, ss = time_s.split(":")
    return datetime(int(y), int(m), int(d), int(hh), int(mm), int(ss), tzinfo=UTC)


def load_pos_orders(path: Path) -> list[PosOrder]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    agg: dict[str, dict] = {}
    for r in rows:
        if r.get("store_id") != STORE_CODE or r.get("invoice_type") != "sales":
            continue
        oid = r["order_id"]
        if oid not in agg:
            agg[oid] = {
                "order_id": oid,
                "invoice_number": r["invoice_number"],
                "occurred_at": _parse_dt(r["order_date"], r["order_time"]),
                "nmv": Decimal("0"),
                "gmv": Decimal("0"),
                "line_count": 0,
                "customer_name": (r.get("customer_name") or "").strip(),
            }
        agg[oid]["nmv"] += Decimal(str(r.get("NMV") or "0"))
        agg[oid]["gmv"] += Decimal(str(r.get("GMV") or "0"))
        agg[oid]["line_count"] += 1
    return [
        PosOrder(
            order_id=v["order_id"],
            invoice_number=v["invoice_number"],
            occurred_at=v["occurred_at"],
            nmv=v["nmv"],
            gmv=v["gmv"],
            line_count=v["line_count"],
            customer_name=v["customer_name"],
        )
        for v in sorted(agg.values(), key=lambda x: x["occurred_at"])
    ]


def analyze_csv_columns(rows: list[dict]) -> dict:
    sample = rows[0] if rows else {}
    return {
        "transaction_columns": [
            "order_id", "invoice_number", "invoice_type", "order_date", "order_time",
            "return_id", "store_id", "store_name", "sku", "product_id", "qty",
        ],
        "revenue_columns": [
            "GMV", "NMV", "total_amount", "coupon_amount", "item_promotion",
            "amt_without_gwp", "taxable_amt", "tax_amt", "pb_eb_sale",
        ],
        "purchase_event_key": "order_id (line items) → invoice_number (receipt)",
        "billing_timestamp_columns": ["order_date", "order_time"],
        "recommended_amount": "NMV (Net Merchandise Value after discounts)",
        "line_count": len(rows),
        "column_count": len(sample),
        "all_columns": list(sample.keys()),
    }


async def _fetch_funnel_and_revenue(period_start: datetime, period_end: datetime) -> dict:
    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton
    from app.domain.dashboard.kpi_queries import sum_completed_revenue
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
        funnel = await svc.get_funnel(DEMO_STORE_ID, from_ts=period_start, to_ts=period_end)
        revenue = await sum_completed_revenue(session, DEMO_STORE_ID, period_start, period_end)
        stages = {s.stage: s for s in funnel.stages}
    await dispose_engine()
    return {
        "unique_visitors": funnel.unique_visitors,
        "stages": stages,
        "revenue": revenue,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


def _pct(num: Decimal | float, den: Decimal | float) -> str:
    if den == 0:
        return "—"
    return f"{float(num) / float(den) * 100:.2f}%"


def _write_report(
    col_analysis: dict,
    orders: list[PosOrder],
    funnel: dict,
    evening_orders: list[PosOrder],
    pilot_orders: list[PosOrder],
) -> Path:
    stages = funnel["stages"]
    visitors = funnel["unique_visitors"]
    billing = stages["BILLING_QUEUE"].count
    purchases = stages["PURCHASE"].count
    revenue = funnel["revenue"]

    pos_revenue = sum(o.nmv for o in orders)
    pos_orders = len(orders)

    conv_billing_purchase = min(purchases, billing) / billing if billing else None
    purchase_rate = min(purchases, visitors) / visitors if visitors else None
    rev_per_visitor = revenue / visitors if visitors else Decimal("0")
    raw_conv = purchases / billing if billing else None
    raw_purchase_rate = purchases / visitors if visitors else None

    lines = [
        "# POS + CCTV Funnel Integration Report",
        "",
        f"**Generated:** {datetime.now(tz=UTC).isoformat()}",
        f"**Store:** Brigade_Bangalore (`{DEMO_STORE_ID}`) · **POS file:** `Brigade_Bangalore_10_April_26.csv`",
        f"**Analysis period:** {funnel['period_start']} → {funnel['period_end']}",
        "",
        "## 1. CSV column identification",
        "",
        "### Transaction columns",
        "",
        "Identifiers and line-item fields used to define a **purchase event**:",
        "",
        "| Column | Role |",
        "|--------|------|",
        "| `order_id` | Transaction / basket ID (multiple line rows per order) |",
        "| `invoice_number` | POS receipt ID (stored as `transactions.external_ref`) |",
        "| `invoice_type` | `sales` = completed purchase; filtered for ingest |",
        "| `order_date` + `order_time` | **Billing timestamp** (DD-MM-YYYY HH:MM:SS) |",
        "| `store_id` / `store_name` | Store filter (`ST1008` / Brigade_Bangalore) |",
        "| `sku`, `product_id`, `qty` | Line-item product detail |",
        "",
        "### Revenue columns",
        "",
        "| Column | Meaning | Used |",
        "|--------|---------|:----:|",
        "| `NMV` | Net Merchandise Value (after discounts) | **Yes** — transaction amount |",
        "| `GMV` | Gross Merchandise Value (list price × qty) | Metadata |",
        "| `total_amount` | Line total including tax adjustments | Cross-check |",
        "| `taxable_amt`, `tax_amt` | Tax breakdown | Metadata |",
        "| `coupon_amount`, `item_promotion` | Discount components | Metadata |",
        "",
        f"**Line rows in CSV:** {col_analysis['line_count']} · **Distinct orders:** {pos_orders}",
        "",
        "### Purchase events",
        "",
        f"- **Key:** `{col_analysis['purchase_event_key']}`",
        f"- **Recommended amount field:** `{col_analysis['recommended_amount']}`",
        f"- **Billing timestamps:** `{', '.join(col_analysis['billing_timestamp_columns'])}`",
        "",
        "## 2. POS summary (real data — 10 April 2026)",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Completed orders | **{pos_orders}** |",
        f"| Line items | {col_analysis['line_count']} |",
        f"| Revenue (NMV) | **₹{pos_revenue:,.2f}** |",
        f"| Revenue (GMV) | ₹{sum(o.gmv for o in orders):,.2f} |",
        f"| First billing | {orders[0].occurred_at.strftime('%H:%M:%S')} |",
        f"| Last billing | {orders[-1].occurred_at.strftime('%H:%M:%S')} |",
        "",
        "### Billing timestamps (sample orders)",
        "",
        "| Time (UTC) | Invoice | NMV (₹) | Customer |",
        "|------------|---------|--------:|----------|",
    ]

    for o in orders[:8]:
        lines.append(
            f"| {o.occurred_at.strftime('%Y-%m-%d %H:%M:%S')} | `{o.invoice_number}` | "
            f"{o.nmv:,.2f} | {o.customer_name or 'Guest'} |"
        )
    lines.append(f"| … | *{pos_orders - 8} more orders* | | |")

    lines.extend([
        "",
        "### Evening window (CCTV pilot overlap ≥ 20:00)",
        "",
        f"| Orders | NMV (₹) |",
        f"|-------:|--------:|",
        f"| {len(evening_orders)} | {sum(o.nmv for o in evening_orders):,.2f} |",
        "",
        f"**CCTV footage window (~20:10–20:12):** {len(pilot_orders)} POS order(s) in 20:10–20:30 band.",
        "",
        "## 3. Integrated funnel (Visitors → Billing Queue → Purchase)",
        "",
        "Stages combine **CCTV vision events** (visitors, billing queue) with **ingested POS transactions** (purchase).",
        "",
        "```",
        "  Visitors (CCTV)     Billing Queue (CCTV)     Purchase (POS)",
        f"       {visitors:>3}        ───────────────►           {billing:>3}        ───────────────►      {purchases:>3}",
        "```",
        "",
        "| Stage | Count | Source |",
        "|-------|------:|--------|",
        f"| **Visitors** | **{visitors}** | CCTV — distinct `external_track_id` (vision pipeline) |",
        f"| **Billing Queue** | **{billing}** | CCTV — first-touch `billing_queue` / `checkout` zone enters |",
        f"| **Purchase** | **{purchases}** | POS — completed `transactions` (NMV, status=completed) |",
        "",
        "## 4. Calculated KPIs (real data)",
        "",
        "| KPI | Formula | Value |",
        "|-----|---------|------:|",
        f"| **Conversion rate** (Billing Queue → Purchase) | min(purchases,billing) / billing_queue | "
        f"**{_pct(conv_billing_purchase, 1) if conv_billing_purchase is not None else '—'}** |",
        f"| **Purchase rate** (Visitors → Purchase) | min(purchases,visitors) / unique_visitors | "
        f"**{_pct(purchase_rate, 1) if purchase_rate is not None else '—'}** |",
        f"| **Revenue** | Σ transaction NMV | **₹{revenue:,.2f}** |",
        f"| **Revenue per visitor** | revenue / unique_visitors | **₹{rev_per_visitor:,.2f}** |",
        "",
        f"*Raw ratios (uncapped): billing→purchase {_pct(raw_conv, 1) if raw_conv else '—'}, "
        f"visitor→purchase {_pct(raw_purchase_rate, 1) if raw_purchase_rate else '—'} — "
        "POS covers full store day (24 orders) while CCTV billing-queue counts come from ~12 min pilot footage.*",
        "",
        "### Funnel stage detail (API/engine)",
        "",
        "| Stage | Count | Re-entries | Conversion | Drop-off |",
        "|-------|------:|-----------:|-----------:|---------:|",
    ])

    for name in ("ENTRY", "ZONE_VISIT", "BILLING_QUEUE", "PURCHASE"):
        s = stages[name]
        conv = f"{s.conversion_rate:.4f}" if s.conversion_rate is not None else "—"
        drop = f"{s.drop_off_rate:.4f}" if s.drop_off_rate is not None else "—"
        lines.append(f"| {name} | {s.count} | {s.re_entry_count} | {conv} | {drop} |")

    lines.extend([
        "",
        "## 5. Data alignment notes",
        "",
        "- **POS billing timestamps** are real store-local times on **10-Apr-2026** (`order_date` + `order_time`).",
        "- **CCTV vision events** in PostgreSQL use pipeline ingest timestamps (~May 2026 reprocessing of April footage).",
        "- Integrated KPIs use a **wide analysis window** spanning both datasets; stages are sourced from real tables, not mock UI values.",
        "- Track-level join (visitor → receipt) is not available without POS–CCTV correlation IDs; counts are stage-level integration.",
        "",
        "## 6. Reproduce",
        "",
        "```bash",
        "python scripts/ingest_pos_csv.py --replace",
        "python scripts/analyze_pos_funnel_integration.py",
        "curl -H \"X-API-Key: purple-demo-key\" \\",
        f"  \"http://localhost:8000/api/v1/stores/{DEMO_STORE_ID}/funnel\"",
        "```",
        "",
        "---",
        "",
        f"*POS orders: {pos_orders} · CCTV visitors: {visitors} · Revenue: ₹{revenue:,.2f}*",
    ])

    out = REPO_ROOT / "docs" / "POS_FUNNEL_INTEGRATION.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


async def main() -> int:
    if not POS_CSV.is_file():
        print(f"ERROR: {POS_CSV} not found")
        return 1

    rows = list(csv.DictReader(POS_CSV.open(encoding="utf-8")))
    col_analysis = analyze_csv_columns(rows)
    orders = load_pos_orders(POS_CSV)

    evening = [o for o in orders if o.occurred_at >= CCTV_PILOT_START]
    pilot = [
        o for o in orders
        if datetime(2026, 4, 10, 20, 10, 0, tzinfo=UTC) <= o.occurred_at <= datetime(2026, 4, 10, 20, 30, 0, tzinfo=UTC)
    ]

    # Ensure POS is ingested
    try:
        subprocess.run(
            [sys.executable, "scripts/ingest_pos_csv.py", "--replace"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
    except subprocess.CalledProcessError as exc:
        print("WARN: POS ingest failed:", exc.stderr or exc.stdout)

    period_start = datetime(2026, 4, 10, 0, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)
    funnel = await _fetch_funnel_and_revenue(period_start, period_end)

    report = _write_report(col_analysis, orders, funnel, evening, pilot)

    json_out = REPO_ROOT / "docs" / "evidence" / "pos_funnel_integration.json"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "column_analysis": col_analysis,
                "pos_orders": len(orders),
                "pos_revenue_nmv": str(sum(o.nmv for o in orders)),
                "funnel": {
                    "unique_visitors": funnel["unique_visitors"],
                    "billing_queue": funnel["stages"]["BILLING_QUEUE"].count,
                    "purchase": funnel["stages"]["PURCHASE"].count,
                    "revenue": str(funnel["revenue"]),
                },
                "evening_orders": len(evening),
                "pilot_window_orders": len(pilot),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {report}")
    print(f"Wrote {json_out}")
    print(
        f"Funnel: visitors={funnel['unique_visitors']} billing={funnel['stages']['BILLING_QUEUE'].count} "
        f"purchase={funnel['stages']['PURCHASE'].count} revenue=INR {funnel['revenue']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
