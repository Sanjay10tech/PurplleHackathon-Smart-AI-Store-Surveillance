#!/usr/bin/env python3
"""Generate REVIEWER_ACCEPTANCE_REPORT.md from live checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "REVIEWER_ACCEPTANCE_REPORT.md"
API_BASE = os.environ.get("REVIEWER_API_BASE", "http://localhost:8000")
STORE_ID = "00000000-0000-0000-0000-000000000101"
API_KEY = os.environ.get("API_KEY", "purple-demo-key")


def _get(path: str, *, auth: bool = False) -> tuple[int, dict | str]:
    headers = {"X-API-Key": API_KEY} if auth else {}
    req = urllib.request.Request(f"{API_BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body[:300]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body[:300]


def _run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = (proc.stdout or proc.stderr).strip().splitlines()
    summary = tail[-1] if tail else f"exit={proc.returncode}"
    return proc.returncode, summary


def _video_status() -> dict[str, object]:
    videos = []
    missing = []
    for i in range(1, 6):
        name = f"CAM {i}.mp4"
        path = REPO_ROOT / "data" / "videos" / name
        if path.is_file():
            videos.append({"name": name, "bytes": path.stat().st_size})
        else:
            missing.append(name)
    bootstrap = REPO_ROOT / "data" / "reviewer" / "yolo_bootstrap_events.jsonl"
    bootstrap_lines = 0
    if bootstrap.is_file():
        bootstrap_lines = sum(1 for line in bootstrap.open(encoding="utf-8") if line.strip())
    return {
        "videos_present": len(videos),
        "videos_missing": missing,
        "bootstrap_events": bootstrap_lines,
    }


def main() -> int:
    now = datetime.now(tz=UTC).isoformat()
    pytest_code, pytest_summary = _run_pytest()
    videos = _video_status()

    endpoints = [
        ("GET /health", False, "/health"),
        ("GET /reviewer", False, "/reviewer"),
        (
            "GET /metrics",
            True,
            f"/api/v1/stores/{STORE_ID}/metrics?metric=visitor.count",
        ),
        ("GET /funnel", True, f"/api/v1/stores/{STORE_ID}/funnel"),
        ("GET /anomalies", True, f"/api/v1/stores/{STORE_ID}/anomalies"),
        (
            "GET /dashboard/summary",
            True,
            f"/api/v1/stores/{STORE_ID}/dashboard/summary",
        ),
    ]

    rows: list[dict[str, object]] = []
    for label, auth, path in endpoints:
        status, body = _get(path, auth=auth)
        rows.append({"label": label, "status": status, "body": body})

    health = rows[0]["body"] if isinstance(rows[0]["body"], dict) else {}
    reviewer = rows[1]["body"] if isinstance(rows[1]["body"], dict) else {}
    metrics = rows[2]["body"] if isinstance(rows[2]["body"], dict) else {}
    funnel = rows[3]["body"] if isinstance(rows[3]["body"], dict) else {}
    anomalies = rows[4]["body"] if isinstance(rows[4]["body"], dict) else {}
    dashboard = rows[5]["body"] if isinstance(rows[5]["body"], dict) else {}

    stages = {s.get("stage"): s.get("count") for s in funnel.get("stages", [])}
    linkage = (dashboard.get("pos_insights") or {}).get("linkage") or {}
    evidence = dashboard.get("reviewer_evidence") or {}
    headline = dashboard.get("reviewer_headline") or {}

    score_checks = [
        pytest_code == 0,
        rows[0]["status"] == 200,
        rows[1]["status"] == 200 and reviewer.get("ready_for_review"),
        rows[2]["status"] == 200 and len(metrics.get("series", [])) >= 0,
        rows[3]["status"] == 200 and funnel.get("unique_visitors", 0) >= 0,
        int(evidence.get("events_generated") or 0) >= 10,
        int(videos["bootstrap_events"]) >= 10,
    ]
    score = int(round(100 * sum(score_checks) / len(score_checks)))

    lines = [
        "# Reviewer Acceptance Report",
        "",
        f"**Generated:** {now}  ",
        f"**API base:** {API_BASE}  ",
        f"**Demo store:** `{STORE_ID}`  ",
        "",
        "## 1. Docker compose verification",
        "",
        "| Check | Result |",
        "|-------|--------|",
        f"| API health | HTTP {rows[0]['status']} — db={health.get('checks', {}).get('database')} feed={health.get('checks', {}).get('feed')} |",
        f"| Reviewer proof | HTTP {rows[1]['status']} — {reviewer.get('checks_passed')}/{reviewer.get('checks_total')} checks, ready={reviewer.get('ready_for_review')} |",
        f"| CCTV bootstrap file | `{videos['bootstrap_events']}` YOLO events committed |",
        f"| Local MP4s present | {videos['videos_present']}/5" + (f" (missing: {', '.join(videos['videos_missing'])})" if videos['videos_missing'] else "") + " |",
        "",
        "## 2. Tests passed",
        "",
        f"```",
        pytest_summary,
        f"```",
        f"**Exit code:** {pytest_code}",
        "",
        "## 3. Videos processed",
        "",
        f"- Dashboard source videos: {evidence.get('source_videos') or []}",
        f"- Videos processed count: {evidence.get('videos_processed', 0)}/5",
        f"- Detector mode: {evidence.get('detector_mode')}",
        f"- Processing lineage: {evidence.get('processing_lineage')}",
        "",
        "## 4. Events generated",
        "",
        f"- Vision events in period: {headline.get('vision_events', evidence.get('events_generated', 0))}",
        f"- Frames analyzed: {evidence.get('frames_analyzed', 0)}",
        f"- Last ingestion: {evidence.get('last_ingestion_at')}",
        "",
        "## 5. Funnel counts",
        "",
        f"| Stage | Count |",
        f"|-------|-------|",
    ]
    for stage, count in stages.items():
        lines.append(f"| {stage} | {count} |")
    lines.extend(
        [
            "",
            f"- Unique visitors: {funnel.get('unique_visitors')}",
            f"- Dedupe strategy: {funnel.get('dedupe_strategy')}",
            "",
            "## 6. Metrics endpoint",
            "",
            f"- HTTP {rows[2]['status']}",
            f"- Metric: {metrics.get('metric')}",
            f"- Series points: {len(metrics.get('series', []))}",
            f"- Unique visitors: {metrics.get('unique_visitors')}",
            f"- Source: {(metrics.get('meta') or {}).get('source')}",
            "",
            "## 7. Anomalies endpoint",
            "",
            f"- HTTP {rows[4]['status']}",
            f"- Items: {len(anomalies.get('items', []))}",
            "",
            "## 8. POS ↔ CCTV linkage",
            "",
            f"- POS purchases (CSV): {headline.get('pos_purchases')}",
            f"- Linked purchases (CCTV↔POS): {headline.get('linked_purchases')}",
            f"- Linkage rate: {linkage.get('linkage_rate')}",
            f"- Algorithm: {linkage.get('algorithm')} (±{linkage.get('window_minutes')} min)",
            f"- Explanation: {linkage.get('explanation')}",
            "",
            "## 9. Endpoint matrix",
            "",
            "| Endpoint | HTTP | Summary |",
            "|----------|------|---------|",
        ]
    )
    for row in rows:
        body = row["body"]
        if isinstance(body, dict):
            if row["label"] == "GET /funnel":
                summary = f"stages={stages}"
            elif row["label"] == "GET /metrics":
                summary = f"series={len(body.get('series', []))}, visitors={body.get('unique_visitors')}"
            elif row["label"] == "GET /anomalies":
                summary = f"items={len(body.get('items', []))}"
            elif row["label"] == "GET /reviewer":
                summary = f"{body.get('checks_passed')}/{body.get('checks_total')}"
            else:
                summary = str(body.get("status") or body.get("checks", {}))[:80]
        else:
            summary = str(body)[:80]
        lines.append(f"| {row['label']} | **{row['status']}** | {summary} |")

    lines.extend(
        [
            "",
            "## 10. Final Purple score (computed from live checks)",
            "",
            f"**Score: {score}/100**",
            "",
            "| Criterion | Pass |",
            "|-----------|------|",
            f"| pytest green | {'✓' if pytest_code == 0 else '✗'} |",
            f"| /health 200 | {'✓' if rows[0]['status'] == 200 else '✗'} |",
            f"| /reviewer ready | {'✓' if reviewer.get('ready_for_review') else '✗'} |",
            f"| metrics 200 | {'✓' if rows[2]['status'] == 200 else '✗'} |",
            f"| funnel 200 | {'✓' if rows[3]['status'] == 200 else '✗'} |",
            f"| vision events ≥ 10 | {'✓' if int(evidence.get('events_generated') or 0) >= 10 else '✗'} |",
            f"| bootstrap committed | {'✓' if int(videos['bootstrap_events']) >= 10 else '✗'} |",
        ]
    )

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(REPORT)
    print(f"Score: {score}/100")
    return 0 if pytest_code == 0 and all(r["status"] == 200 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
