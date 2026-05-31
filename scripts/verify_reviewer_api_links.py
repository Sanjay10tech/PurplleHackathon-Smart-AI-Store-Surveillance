"""Verify reviewer-facing API URLs return expected HTTP status."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API_BASE = os.environ.get("REVIEWER_API_BASE", "http://localhost:8000")
STORE_ID = "00000000-0000-0000-0000-000000000101"
API_KEY = os.environ.get("API_KEY", "purple-demo-key")
REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "docs" / "REVIEWER_API_VERIFICATION.md"


def _get(path: str, *, auth: bool = False) -> tuple[int, dict | str]:
    headers = {"X-API-Key": API_KEY} if auth else {}
    req = urllib.request.Request(f"{API_BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body[:200]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body[:200]


def _summary(path: str, status: int, body: dict | str) -> str:
    if not isinstance(body, dict):
        return str(body)[:120]
    if path == "/health":
        return f"status={body.get('status')}, db={body.get('checks', {}).get('database')}"
    if path == "/reviewer":
        return f"checks={body.get('checks_passed')}/{body.get('checks_total')}, ready={body.get('ready_for_review')}"
    if path.endswith("/metrics"):
        return f"metric={body.get('metric')}, series={len(body.get('series', []))}, visitors={body.get('unique_visitors')}"
    if path.endswith("/funnel"):
        stages = {s.get("stage"): s.get("count") for s in body.get("stages", [])}
        return f"stages={stages}"
    if path.endswith("/heatmap"):
        return f"zones={len(body.get('zones', []))}, visits={sum(z.get('visit_count', 0) for z in body.get('zones', []))}"
    if path.endswith("/anomalies"):
        return f"items={len(body.get('items', []))}"
    if path.endswith("/dashboard/summary"):
        kpis = {k["key"]: k.get("value") for k in body.get("kpis", []) if k["key"] in ("purchases", "total_entries", "revenue")}
        return f"kpis={kpis}"
    if path.endswith("/funnel/journeys"):
        return f"journeys={len(body.get('journeys', []))}"
    if path.endswith("/reid/evidence"):
        return f"cross_camera={body.get('cross_camera_track_count', 0)}"
    return "ok"


def main() -> int:
    routes: list[tuple[str, bool, str]] = [
        ("GET /health", False, "/health"),
        ("GET /reviewer", False, "/reviewer"),
        ("GET /health/ready", False, "/health/ready"),
        (
            "GET /metrics",
            True,
            f"/api/v1/stores/{STORE_ID}/metrics?metric=visitor.count",
        ),
        ("GET /funnel", True, f"/api/v1/stores/{STORE_ID}/funnel"),
        ("GET /heatmap", True, f"/api/v1/stores/{STORE_ID}/heatmap"),
        ("GET /anomalies", True, f"/api/v1/stores/{STORE_ID}/anomalies"),
        (
            "GET /dashboard/summary",
            True,
            f"/api/v1/stores/{STORE_ID}/dashboard/summary",
        ),
        (
            "GET /funnel/journeys",
            True,
            f"/api/v1/stores/{STORE_ID}/funnel/journeys",
        ),
        (
            "GET /reid/evidence",
            True,
            f"/api/v1/stores/{STORE_ID}/reid/evidence",
        ),
    ]

    rows: list[dict[str, object]] = []
    failed = 0
    for label, auth, path in routes:
        status, body = _get(path, auth=auth)
        ok = status == 200
        if not ok:
            failed += 1
        rows.append(
            {
                "label": label,
                "url": f"{API_BASE}{path}",
                "auth": "X-API-Key" if auth else "none",
                "status": status,
                "ok": ok,
                "summary": _summary(path, status, body),
            }
        )

    now = datetime.now(tz=UTC).isoformat()
    lines = [
        "# Reviewer API Verification Report",
        "",
        f"**Generated:** {now}  ",
        f"**API base:** {API_BASE}  ",
        f"**Demo store:** `{STORE_ID}`  ",
        f"**API key:** `{API_KEY}` (header `X-API-Key`)",
        "",
        "| Endpoint | URL | Auth | HTTP | Summary |",
        "|----------|-----|------|------|---------|",
    ]
    for row in rows:
        mark = "✓" if row["ok"] else "✗"
        lines.append(
            f"| {row['label']} | `{row['url']}` | {row['auth']} | **{row['status']}** {mark} | {row['summary']} |"
        )
    lines.extend(
        [
            "",
            "## Curl quick-start",
            "",
            "```bash",
            f"curl {API_BASE}/health",
            f"curl {API_BASE}/reviewer",
            f'curl -H "X-API-Key: {API_KEY}" "{API_BASE}/api/v1/stores/{STORE_ID}/metrics?metric=visitor.count"',
            f'curl -H "X-API-Key: {API_KEY}" "{API_BASE}/api/v1/stores/{STORE_ID}/funnel"',
            f'curl -H "X-API-Key: {API_KEY}" "{API_BASE}/api/v1/stores/{STORE_ID}/anomalies"',
            "```",
            "",
            f"**Result:** {len(rows) - failed}/{len(rows)} endpoints returned HTTP 200",
        ]
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(REPORT_PATH)
    for row in rows:
        mark = "PASS" if row["ok"] else "FAIL"
        print(f"[{mark}] {row['status']} {row['label']} — {row['summary']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
