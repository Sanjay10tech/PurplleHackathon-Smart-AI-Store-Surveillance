#!/usr/bin/env python3
"""Audit dashboard API connectivity and write DASHBOARD_DEBUG_REPORT.md."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "DASHBOARD_DEBUG_REPORT.md"
STORE = "00000000-0000-0000-0000-000000000101"
KEY = "purple-demo-key"
HOSTS = ("localhost", "127.0.0.1")
TIMEOUT = 12


def _probe(host: str, path: str, *, auth: bool = True) -> dict:
    url = f"http://{host}:8000{path}"
    headers = {"X-API-Key": KEY} if auth and "/stores/" in path else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            parsed = None
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
            return {
                "url": url,
                "status": resp.status,
                "ok": resp.status < 400,
                "body_preview": body[:200],
                "parsed_hint": _hint(path, parsed),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        return {
            "url": url,
            "status": exc.code,
            "ok": False,
            "body_preview": body[:200],
            "parsed_hint": body[:120],
        }
    except Exception as exc:
        return {
            "url": url,
            "status": None,
            "ok": False,
            "body_preview": "",
            "parsed_hint": str(exc),
        }


def _hint(path: str, data: dict | None) -> str:
    if not isinstance(data, dict):
        return "non-JSON"
    if path.endswith("/dashboard/summary"):
        kpis = data.get("kpis") or []
        return f"kpis={len(kpis)} partial={data.get('meta', {}).get('partial')}"
    if path.endswith("/funnel"):
        stages = data.get("stages") or []
        return f"stages={len(stages)} visitors={data.get('unique_visitors')}"
    if path.endswith("/metrics"):
        return f"series={len(data.get('series') or [])}"
    if path.endswith("/anomalies"):
        return f"items={len(data.get('items') or data.get('anomalies') or [])}"
    if path == "/health":
        return f"status={data.get('status')} db={data.get('checks', {}).get('database')}"
    return "ok"


def main() -> int:
    paths = [
        ("/health", False),
        ("/dashboard/", False),
        (f"/api/v1/stores/{STORE}/dashboard/summary", True),
        (f"/api/v1/stores/{STORE}/metrics", True),
        (f"/api/v1/stores/{STORE}/funnel", True),
        (f"/api/v1/stores/{STORE}/anomalies", True),
        (f"/api/v1/stores/{STORE}/heatmap", True),
        (f"/api/v1/stores/{STORE}/funnel/journeys", True),
        (f"/api/v1/stores/{STORE}", True),
    ]

    rows: list[dict] = []
    for host in HOSTS:
        for path, auth in paths:
            rows.append({"host": host, **_probe(host, path, auth=auth)})

    failed = [r for r in rows if not r["ok"]]
    localhost_ok = all(r["ok"] for r in rows if r["host"] == "localhost")

    lines = [
        "# Dashboard Debug Report",
        "",
        f"**Generated:** {datetime.now(tz=UTC).isoformat()}",
        f"**Store ID:** `{STORE}`",
        f"**API key tested:** `{KEY}`",
        "",
        "## API request matrix",
        "",
        "| Host | Path | Status | Result | Hint |",
        "|------|------|-------:|--------|------|",
    ]
    for r in rows:
        status = r["status"] if r["status"] is not None else "ERR"
        result = "PASS" if r["ok"] else "**FAIL**"
        path = r["url"].split(":8000", 1)[-1]
        lines.append(f"| {r['host']} | `{path}` | {status} | {result} | {r['parsed_hint']} |")

    lines.extend([
        "",
        "## Failed requests",
        "",
    ])
    if failed:
        for r in failed:
            lines.append(f"- `{r['url']}` → {r['status']} — {r['parsed_hint']}")
    else:
        lines.append("- None (all probed endpoints returned HTTP 2xx)")

    lines.extend([
        "",
        "## Dashboard fetch map (index.html)",
        "",
        "| # | Method | Path | Auth | Required |",
        "|---|--------|------|------|----------|",
        "| 1 | GET | `/api/v1/stores/{store_id}/dashboard/summary` | X-API-Key | yes |",
        "| 2 | GET | `/api/v1/stores/{store_id}/funnel` | X-API-Key | yes |",
        "| 3 | GET | `/api/v1/stores/{store_id}/heatmap` | X-API-Key | yes |",
        "| 4 | GET | `/api/v1/stores/{store_id}/metrics` | X-API-Key | yes |",
        "| 5 | GET | `/api/v1/stores/{store_id}/anomalies` | X-API-Key | optional |",
        "| 6 | GET | `/api/v1/stores/{store_id}/funnel/journeys` | X-API-Key | optional |",
        "| 7 | GET | `/health` | none | optional |",
        "",
        "## Root cause analysis",
        "",
    ])

    if not localhost_ok:
        lines.extend([
            "### Primary: API backend unavailable or erroring",
            "",
            "The dashboard UI loads from `/dashboard/` (static HTML) but widgets call store analytics APIs.",
            "When any **required** endpoint returns 401/404/500 or **hangs**, `refresh()` fails and KPI cards stay at `—`.",
            "",
            "**Common causes:**",
            "- Stale local `uvicorn` on port 8000 without PostgreSQL (HTTP 500 on all routes)",
            "- Docker stack not running (`docker compose up -d`)",
            "- Missing/wrong `X-API-Key` when `API_KEY_REQUIRED=true` (HTTP 401)",
            "- Wrong store UUID (HTTP 404)",
            "- No fetch timeout → hung server leaves UI on *Fetching live pipeline data…*",
            "",
        ])
    else:
        lines.extend([
            "### APIs healthy — empty widgets likely mean no ingested pipeline data",
            "",
            f"All endpoints returned 200. Fresh Docker boot seeds demo store `{STORE}` but KPI values are **0** until",
            "CCTV pipeline events are ingested (`python -m pipeline.run --ingest --camera \"CAM 3\"`).",
            "",
        ])

    lines.extend([
        "## Fixes applied",
        "",
        "- `dashboard/index.html`: 15s fetch timeout; resilient optional endpoints; clearer 401/404 hints",
        "- Run `docker compose up -d` before opening dashboard",
        "- Use API key `purple-demo-key` (pre-filled in dashboard)",
        "",
        "## Verification",
        "",
        "```bash",
        "docker compose up -d",
        "python scripts/verify_dashboard_apis.py",
        "python scripts/diagnose_dashboard.py",
        "# open http://localhost:8000/dashboard/",
        "```",
        "",
    ])

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT}")
    print(f"Failed: {len(failed)} / {len(rows)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
