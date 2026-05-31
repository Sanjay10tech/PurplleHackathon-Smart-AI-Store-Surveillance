#!/usr/bin/env python3
"""
Generate Purple Tech evaluation evidence from real pipeline + ingested DB data.

Writes:
  - docs/evidence/evaluation_evidence.json
  - docs/evidence/evaluation_run.log
  - docs/EVIDENCE.md
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"
DEMO_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")


def _load_detection_validation() -> dict:
    path = EVIDENCE_DIR / "detection_validation.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _pick_screenshots() -> list[dict]:
    """Representative YOLO annotated frames (real detection evidence)."""
    picks = [
        ("CAM 3", "CAM_3_frame_005.jpg", "Entry camera — person at door threshold"),
        ("CAM 3", "CAM_3_frame_012.jpg", "Entry camera — track with bounding box"),
        ("CAM 1", "CAM_1_frame_003.jpg", "Floor camera — aisle detection"),
        ("CAM 2", "CAM_2_frame_008.jpg", "Cosmetics aisle — multi-person frame"),
        ("CAM 5", "CAM_5_frame_004.jpg", "Billing counter — staff/visitor boxes"),
    ]
    tracking = EVIDENCE_DIR / "tracking"
    out = []
    for cam, fname, caption in picks:
        path = EVIDENCE_DIR / "annotated" / fname
        if path.is_file():
            out.append({
                "camera": cam,
                "file": f"annotated/{fname}",
                "caption": caption,
            })
    for tname in ("CAM_3_tracking.jpg", "CAM_1_tracking.jpg", "CAM_5_tracking.jpg"):
        tpath = tracking / tname
        if tpath.is_file():
            out.append({
                "camera": tname.replace("_tracking.jpg", "").replace("_", " "),
                "file": f"tracking/{tname}",
                "caption": "Tracking overlay — ByteTrack IDs on sampled frame",
            })
            break
    return out


def _run_log_capture() -> str:
    lines: list[str] = []
    commands = [
        [sys.executable, "scripts/audit_funnel.py"],
    ]
    env = os.environ.copy()
    url = env.get("DATABASE_URL", "postgresql+asyncpg://si:si@localhost:5432/store_intelligence")
    env["DATABASE_URL"] = url

    for cmd in commands:
        lines.append(f"$ {' '.join(cmd)}")
        lines.append("-" * 72)
        try:
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            lines.append(proc.stdout)
            if proc.stderr:
                lines.append(proc.stderr)
            lines.append(f"[exit {proc.returncode}]")
        except Exception as exc:
            lines.append(f"ERROR: {exc}")
        lines.append("")

    dv = _load_detection_validation()
    if dv:
        lines.append("--- YOLO full validation (validate_detection.py) ---")
        lines.append(f"correlation_id: {dv.get('correlation_id')}")
        lines.append(f"videos_processed: {dv.get('videos_processed')}")
        lines.append(f"total_frames_processed: {dv.get('total_frames_processed')}")
        lines.append(f"total_people_detections: {dv.get('total_people_detections')}")
        lines.append(f"total_entry_events: {dv.get('total_entry_events')}")
        lines.append(f"processing_seconds: {dv.get('accuracy', {}).get('processing_seconds')}")
        lines.append("")

    jsonl = REPO_ROOT / "data" / "pipeline" / "events.jsonl"
    if jsonl.is_file():
        count = sum(1 for line in jsonl.open(encoding="utf-8") if line.strip())
        lines.append(f"--- Pipeline JSONL ---")
        lines.append(f"path: {jsonl.relative_to(REPO_ROOT)}")
        lines.append(f"events_written: {count}")
        lines.append("")

    return "\n".join(lines)


async def _collect_db_metrics() -> dict:
    from sqlalchemy import text

    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton
    from app.dependencies import get_anomaly_service, get_dashboard_service, get_funnel_service, get_heatmap_service, get_analytics_service, get_store_repository
    from app.database import get_db_session

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = url
    reset_engine_singleton()

    store = DEMO_STORE_ID
    metrics: dict = {}

    engine = create_engine()
    sf = create_session_factory(engine)

    async with sf() as session:
        from app.domain.dashboard.kpi_queries import (
            count_pipeline_events,
            count_reentry_events,
            count_staff_filtered_events,
            count_store_entry_events,
            count_store_exit_events,
        )

        now = datetime.now(tz=UTC)
        period_start = now - timedelta(hours=24 * 365)
        period_end = now

        row = await session.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM events WHERE store_id = :store
                     AND event_type = 'vision.zone.entered'
                     AND COALESCE(payload->>'class_label','') != 'staff'
                     AND COALESCE(payload->>'zone_type','') NOT IN ('staff_only','ignore')
                  ) AS zone_visit_events,
                  (SELECT COUNT(*) FROM events WHERE store_id = :store
                     AND event_type = 'vision.zone.entered'
                     AND payload->>'zone_type' IN ('billing_queue','checkout','queue','billing')
                     AND COALESCE(payload->>'class_label','') != 'staff'
                  ) AS queue_events,
                  (SELECT COUNT(*) FROM transactions WHERE store_id = :store
                     AND status = 'completed') AS purchases,
                  (SELECT COUNT(*) FROM events WHERE store_id = :store) AS total_events
                """
            ),
            {"store": str(store)},
        )
        sql = dict(row.one()._mapping)

        metrics.update({
            "entries": await count_store_entry_events(session, store, period_start, period_end),
            "exits": await count_store_exit_events(session, store, period_start, period_end),
            "re_entries": await count_reentry_events(session, store, period_start, period_end),
            "staff_filtered": await count_staff_filtered_events(session, store, period_start, period_end),
            "zone_visits": int(sql["zone_visit_events"]),
            "queue_events": int(sql["queue_events"]),
            "purchases": int(sql["purchases"]),
            "total_events_ingested": int(sql["total_events"]),
        })

        from app.repositories.event_repository import EventRepository
        from app.repositories.funnel_repository import FunnelRepository
        from app.repositories.store_repository import StoreRepository
        from app.repositories.heatmap_repository import HeatmapRepository
        from app.repositories.anomaly_repository import AnomalyRepository
        from app.repositories.store_metric_repository import StoreMetricRepository
        from app.services.dashboard_service import DashboardService
        from app.services.funnel_service import FunnelService
        from app.services.heatmap_service import HeatmapService
        from app.services.analytics_service import AnalyticsService
        from app.services.anomaly_service import AnomalyService

        store_repo = StoreRepository(session)
        funnel_svc = FunnelService(FunnelRepository(session), store_repo, EventRepository(session))
        heatmap_svc = HeatmapService(HeatmapRepository(session), store_repo)
        analytics_svc = AnalyticsService(
            StoreMetricRepository(session), store_repo, EventRepository(session), AnomalyRepository(session)
        )
        anomaly_svc = AnomalyService(
            HeatmapRepository(session), FunnelRepository(session), store_repo,
            AnomalyRepository(session), EventRepository(session),
        )
        dash_svc = DashboardService(
            session, store_repo, funnel_svc, heatmap_svc, analytics_svc, anomaly_svc
        )

        summary = await dash_svc.get_summary(store)
        funnel = await funnel_svc.get_funnel(store)
        anomalies = await anomaly_svc.get_anomalies(store)

        metrics["re_entries_funnel"] = sum(s.re_entry_count for s in funnel.stages)
        metrics["re_entries"] = max(metrics["re_entries"], metrics["re_entries_funnel"])
        metrics["anomalies"] = len(anomalies.items)
        metrics["unique_visitors"] = funnel.unique_visitors
        metrics["funnel_stages"] = {s.stage: s.count for s in funnel.stages}
        metrics["heatmap_total_visits"] = int(summary.provenance.pipeline_events and 0 or 0)
        heatmap = await heatmap_svc.get_heatmap(store)
        metrics["heatmap_total_visits"] = int(heatmap.meta.get("total_visits", 0))

    await dispose_engine()
    return metrics


def _build_bundle(detection: dict, db: dict, screenshots: list[dict], log_text: str) -> dict:
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "store_id": str(DEMO_STORE_ID),
        "data_policy": "real_processed_only",
        "detection_pipeline": {
            "model": detection.get("detector_model", "yolo11n.pt"),
            "mode": detection.get("detector_mode", "yolo"),
            "correlation_id": detection.get("correlation_id"),
            "videos_processed": detection.get("videos_processed", 0),
            "total_frames_analyzed": detection.get("total_frames_processed", 0),
            "people_detected": detection.get("total_people_detections", 0),
            "processing_seconds": detection.get("accuracy", {}).get("processing_seconds"),
            "per_video": detection.get("cameras", []),
        },
        "ingested_intelligence": {
            "total_events": db.get("total_events_ingested", 0),
            "entries": db.get("entries", 0),
            "exits": db.get("exits", 0),
            "re_entries": db.get("re_entries", 0),
            "staff_filtered": db.get("staff_filtered", 0),
            "zone_visits": db.get("zone_visits", 0),
            "heatmap_total_visits": db.get("heatmap_total_visits", 0),
            "queue_events": db.get("queue_events", 0),
            "purchases": db.get("purchases", 0),
            "anomalies": db.get("anomalies", 0),
            "unique_visitors": db.get("unique_visitors", 0),
            "funnel_stages": db.get("funnel_stages", {}),
        },
        "screenshots": screenshots,
        "log_excerpt": log_text[-12000:],
    }


def _write_evidence_md(bundle: dict) -> None:
    det = bundle["detection_pipeline"]
    ing = bundle["ingested_intelligence"]
    lines = [
        "# Evaluation Evidence — Purple Tech",
        "",
        f"**Generated:** {bundle['generated_at']}",
        f"**Store:** `{bundle['store_id']}`",
        "**Policy:** All figures from real YOLO pipeline runs and PostgreSQL ingested events — no mock UI data.",
        "",
        "## Executive summary",
        "",
        "| Metric | Value | Source |",
        "|--------|------:|--------|",
        f"| Videos processed | **{det['videos_processed']}** | YOLO validation — all CCTV MP4s |",
        f"| Total frames analyzed | **{det['total_frames_analyzed']:,}** | Sampled @ 5 FPS, YOLOv11n |",
        f"| People detected | **{det['people_detected']:,}** | Track-frame detections (validation run) |",
        f"| Entries | **{ing['entries']}** | Ingested `is_store_entry` events |",
        f"| Exits | **{ing['exits']}** | Ingested `is_store_exit` events |",
        f"| Re-entries | **{ing['re_entries']}** | Ingested + funnel re_entry_count |",
        f"| Staff filtered | **{ing['staff_filtered']}** | Staff events + staff sessions excluded |",
        f"| Zone visits | **{ing['zone_visits']}** | Customer `vision.zone.entered` events |",
        f"| Queue events | **{ing['queue_events']}** | Billing/checkout zone enters |",
        f"| Purchases | **{ing['purchases']}** | Completed transactions |",
        f"| Anomalies | **{ing['anomalies']}** | Anomaly engine (computed window) |",
        "",
        "## Per-video processing (YOLO real)",
        "",
        "| Video | Frames | People det. | Entry | Zone enters | Staff tracks |",
        "|-------|-------:|------------:|------:|------------:|-------------:|",
    ]

    for cam in det.get("per_video", []):
        lines.append(
            f"| {cam.get('video_file', cam.get('camera_name'))} "
            f"| {cam.get('frames_processed', 0)} "
            f"| {cam.get('people_detected', 0)} "
            f"| {cam.get('entry_events', 0)} "
            f"| {cam.get('zone_enter_events', 0)} "
            f"| {cam.get('staff_tracks_classified', 0)} |"
        )

    lines.extend([
        "",
        "## Ingested funnel (PostgreSQL)",
        "",
        f"| Stage | Count |",
        f"|-------|------:|",
    ])
    for stage, count in ing.get("funnel_stages", {}).items():
        lines.append(f"| {stage} | {count} |")

    lines.extend([
        "",
        f"- Unique visitors (distinct tracks): **{ing['unique_visitors']}**",
        f"- Heatmap total visits (aggregated): **{ing['heatmap_total_visits']}**",
        f"- Total ingested events: **{ing['total_events']}**",
        "",
        "## Detection screenshots",
        "",
        "Real YOLOv11n bounding boxes on CCTV frames (`docs/evidence/annotated/`).",
        "",
    ])

    for shot in bundle.get("screenshots", []):
        lines.append(f"### {shot['camera']} — {shot['caption']}")
        lines.append("")
        lines.append(f"![{shot['caption']}](evidence/{shot['file']})")
        lines.append("")

    lines.extend([
        "",
        "## Processing logs",
        "",
        "```text",
        bundle.get("log_excerpt", "").strip(),
        "```",
        "",
        "## Verification commands",
        "",
        "```bash",
        "python scripts/generate_evaluation_evidence.py",
        "python scripts/validate_detection.py",
        "python scripts/audit_funnel.py",
        "curl -H \"X-API-Key: purple-demo-key\" \\",
        f"  http://localhost:8000/api/v1/stores/{bundle['store_id']}/dashboard/summary",
        "```",
        "",
        "## Live evidence page",
        "",
        "Open **`/dashboard/evidence.html`** for the interactive evaluation view.",
        "",
        "---",
        "",
        f"*Pipeline correlation:* `{det.get('correlation_id', '—')}` · "
        f"*Model:* `{det.get('model')}` · "
        f"*Processing time:* {det.get('processing_seconds', '—')}s",
    ])

    (REPO_ROOT / "docs" / "EVIDENCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    detection = _load_detection_validation()
    if not detection:
        print("WARN: docs/evidence/detection_validation.json missing — run validate_detection.py first")

    db = await _collect_db_metrics()
    screenshots = _pick_screenshots()
    log_text = _run_log_capture()

    bundle = _build_bundle(detection, db, screenshots, log_text)

    json_path = EVIDENCE_DIR / "evaluation_evidence.json"
    json_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    log_path = EVIDENCE_DIR / "evaluation_run.log"
    log_path.write_text(log_text, encoding="utf-8")

    _write_evidence_md(bundle)

    print(f"Wrote {REPO_ROOT / 'docs' / 'EVIDENCE.md'}")
    print(f"Wrote {json_path}")
    print(f"Wrote {log_path}")
    print("\nSummary:")
    print(f"  videos={bundle['detection_pipeline']['videos_processed']} "
          f"frames={bundle['detection_pipeline']['total_frames_analyzed']} "
          f"people={bundle['detection_pipeline']['people_detected']}")
    print(f"  entries={bundle['ingested_intelligence']['entries']} "
          f"exits={bundle['ingested_intelligence']['exits']} "
          f"anomalies={bundle['ingested_intelligence']['anomalies']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
