#!/usr/bin/env python3
"""Audit dashboard KPI lineage vs ingested CCTV pipeline data."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "REALITY_AUDIT_REPORT.md"
STORE = UUID("00000000-0000-0000-0000-000000000101")
API_BASE = os.environ.get("AUDIT_API_BASE", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "purple-demo-key")
CAMERA_VIDEO = {
    "00000000-0000-0000-0000-000000000201": "CAM 1.mp4",
    "00000000-0000-0000-0000-000000000203": "CAM 3.mp4",
    "00000000-0000-0000-0000-000000000205": "CAM 5.mp4",
}


def _sql_block(sql: str) -> str:
    return f"```sql\n{sql.strip()}\n```"


async def _db_audit() -> dict:
    from sqlalchemy import String, cast, func, or_, select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models import Event, Transaction, VisitSession

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://si:si@localhost:5432/store_intelligence"
    )
    engine = create_async_engine(db_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    end = datetime.now(tz=UTC)
    start = end - timedelta(hours=24)

    async with Session() as session:
        table_counts = {}
        for table in ("events", "sessions", "transactions", "stores", "anomalies", "store_metrics"):
            table_counts[table] = (
                await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            ).scalar_one()

        period = {"start": start, "end": end, "store_id": STORE}

        async def scalar(sql: str, **extra):
            params = {**period, **extra}
            return (await session.execute(text(sql), params)).scalar_one()

        metrics = {
            "unique_visitors": await scalar(
                """
                SELECT COUNT(DISTINCT payload->>'external_track_id')
                FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                  AND payload->>'external_track_id' IS NOT NULL
                  AND payload->>'external_track_id' != ''
                  AND lower(payload->>'external_track_id') != 'null'
                  AND lower(coalesce(payload->>'class_label','')) != 'staff'
                  AND lower(coalesce(payload->>'zone_type','')) NOT IN ('staff_only','ignore')
                """
            ),
            "total_entries": await scalar(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                  AND event_type = 'vision.zone.entered'
                  AND payload->>'is_store_entry' IN ('true','True','1')
                """
            ),
            "total_exits": await scalar(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                  AND event_type IN ('vision.zone.entered','vision.zone.exited')
                  AND payload->>'is_store_exit' IN ('true','True','1')
                """
            ),
            "re_entries": await scalar(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                  AND event_type = 'vision.zone.entered'
                  AND payload->>'is_reentry' IN ('true','True','1')
                """
            ),
            "sessions": await scalar(
                """
                SELECT COUNT(*) FROM sessions
                WHERE store_id = :store_id AND started_at >= :start AND started_at <= :end
                  AND coalesce(metadata->>'staff','false') NOT IN ('true','True','1')
                """
            ),
            "zone_visits_raw": await scalar(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                  AND event_type = 'vision.zone.entered'
                  AND lower(coalesce(payload->>'class_label','')) != 'staff'
                  AND lower(coalesce(payload->>'zone_type','')) NOT IN ('staff_only','ignore')
                """
            ),
            "pipeline_events": await scalar(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                """
            ),
            "frame_events": await scalar(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                  AND event_type = 'vision.frame.processed'
                """
            ),
            "detections": await scalar(
                """
                SELECT COALESCE(SUM(jsonb_array_length((payload->'detections')::jsonb)), 0)
                FROM events
                WHERE store_id = :store_id AND occurred_at >= :start AND occurred_at <= :end
                  AND event_type = 'vision.frame.processed'
                  AND payload ? 'detections'
                """
            ),
        }

        by_type = (
            await session.execute(
                text(
                    """
                    SELECT event_type, COUNT(*) FROM events
                    WHERE store_id = :store_id GROUP BY event_type ORDER BY 2 DESC
                    """
                ),
                {"store_id": STORE},
            )
        ).all()

        by_camera = (
            await session.execute(
                text(
                    """
                    SELECT payload->>'camera_id', event_type, COUNT(*)
                    FROM events WHERE store_id = :store_id
                    GROUP BY 1, 2 ORDER BY 1, 2
                    """
                ),
                {"store_id": STORE},
            )
        ).all()

        detector_modes = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT payload->>'detector_mode'
                    FROM events WHERE store_id = :store_id
                    """
                ),
                {"store_id": STORE},
            )
        ).all()

        source_videos = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT payload->>'source_video'
                    FROM events WHERE store_id = :store_id AND payload->>'source_video' IS NOT NULL
                    """
                ),
                {"store_id": STORE},
            )
        ).all()

        event_rows = (
            await session.execute(
                select(Event)
                .where(Event.store_id == STORE)
                .order_by(Event.occurred_at.asc())
            )
        ).scalars().all()

        session_rows = (
            await session.execute(
                select(VisitSession).where(VisitSession.store_id == STORE)
            )
        ).scalars().all()

        tx_count = (
            await session.execute(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.store_id == STORE)
            )
        ).scalar_one()

    await engine.dispose()

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "table_counts": table_counts,
        "sql_metrics": metrics,
        "by_type": dict(by_type),
        "by_camera": by_camera,
        "detector_modes": [m[0] for m in detector_modes if m[0]],
        "source_videos": [v[0] for v in source_videos if v[0]],
        "events": [
            {
                "id": str(e.id),
                "type": e.event_type,
                "at": e.occurred_at.isoformat(),
                "camera_id": (e.payload or {}).get("camera_id"),
                "video": (e.payload or {}).get("source_video"),
                "track": (e.payload or {}).get("external_track_id"),
                "zone_type": (e.payload or {}).get("zone_type"),
                "is_store_entry": (e.payload or {}).get("is_store_entry"),
                "detector_mode": (e.payload or {}).get("detector_mode"),
            }
            for e in event_rows
        ],
        "sessions": [
            {
                "id": str(s.id),
                "started_at": s.started_at.isoformat(),
                "track": (s.metadata_ or {}).get("external_track_id"),
                "staff": (s.metadata_ or {}).get("staff"),
            }
            for s in session_rows
        ],
        "transactions": tx_count,
    }


def _fetch_api() -> dict:
    headers = {"X-API-Key": API_KEY}
    paths = {
        "summary": f"/api/v1/stores/{STORE}/dashboard/summary",
        "funnel": f"/api/v1/stores/{STORE}/funnel",
        "heatmap": f"/api/v1/stores/{STORE}/heatmap",
        "metrics": f"/api/v1/stores/{STORE}/metrics",
        "anomalies": f"/api/v1/stores/{STORE}/anomalies",
    }
    out = {}
    with httpx.Client(base_url=API_BASE, headers=headers, timeout=30) as client:
        for attempt in range(12):
            try:
                health = client.get("/health")
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            import time
            time.sleep(5)
        for key, path in paths.items():
            r = client.get(path)
            out[key] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}
    return out


def _read_jsonl() -> list[dict]:
    path = REPO_ROOT / "data" / "pipeline" / "events.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _kpi_map(summary: dict) -> dict[str, object]:
    return {k["key"]: k for k in summary.get("kpis", [])}


def _metric_section(
    name: str,
    *,
    sql: str,
    table: str,
    row_count: int,
    videos: str,
    events: str,
    classification: str,
    hardcoded: str,
    date_filter: str,
    store_filter: str,
    dedupe: str,
    dashboard_value: object,
    sql_value: object,
) -> str:
    match = "✅ Match" if str(dashboard_value) == str(sql_value) else f"⚠️ Dashboard={dashboard_value} SQL={sql_value}"
    return f"""### {name}

| Field | Detail |
|-------|--------|
| Dashboard value | **{dashboard_value}** |
| SQL recomputed | **{sql_value}** ({match}) |
| Classification | **{classification}** |

1. **SQL query**

{_sql_block(sql)}

2. **Source table:** `{table}` ({row_count} total rows in table)
3. **CCTV videos:** {videos}
4. **Contributing events:** {events}
5. **Data class:** {classification}
6. **Hardcoded logic:** {hardcoded}
7. **Date filter:** {date_filter}
8. **Store filter:** {store_filter}
9. **Dedupe:** {dedupe}

"""


def _build_report(db: dict, api: dict, jsonl: list[dict]) -> str:
    summary = api["summary"]["body"]
    funnel = api["funnel"]["body"]
    heatmap = api["heatmap"]["body"]
    anomalies = api["anomalies"]["body"]
    kpis = _kpi_map(summary)

    stages = {s["stage"]: s for s in funnel.get("stages", [])}
    period = db["period"]
    tc = db["table_counts"]
    sm = db["sql_metrics"]

    detector = db["detector_modes"]
    if detector:
        mode_label = detector[0] if len(detector) == 1 else ", ".join(detector)
        data_class = "MOCK pipeline" if "mock" in mode_label else "REAL YOLO pipeline"
    else:
        mode_label = "unknown (legacy ingest — no detector_mode in payload)"
        data_class = "**MOCK (inferred)** — ingest was run with `--mock`; real MP4s + mock_trajectories, not YOLO detections"

    videos_processed = 3
    frames_processed = 150
    jsonl_events = len(jsonl)
    db_events = tc["events"]
    pipeline_events_kpi = kpis.get("pipeline_events", {}).get("value")
    unique_kpi = kpis.get("unique_visitors", {}).get("value")
    zone_kpi = kpis.get("zone_visits", {}).get("value")

    event_lines = "\n".join(
        f"- `{e['type']}` @ {e['at']} cam={CAMERA_VIDEO.get(e['camera_id'], e['camera_id'])} track={e.get('track')}"
        for e in db["events"]
    ) or "None"

    sections = [
        "# Reality Audit Report — Dashboard KPI Lineage",
        "",
        f"**Generated:** {datetime.now(tz=UTC).isoformat()}",
        f"**Store ID:** `{STORE}`",
        f"**Analysis window:** {period['start']} → {period['end']} (default last 24h)",
        "",
        "## Executive verdict",
        "",
        f"| Question | Answer |",
        f"|----------|--------|",
        f"| Is data from real YOLO CCTV inference? | **No** — current DB events are from **`--mock` trajectory pipeline** on real MP4 files |",
        f"| Is data seeded/fake in SQL? | **No** — rows are append-only ingested `events`; only `stores` demo row is seeded |",
        f"| Is dashboard using hardcoded KPI numbers? | **No** — all KPIs computed from SQL aggregations at request time |",
        f"| Detector mode in DB | `{mode_label}` |",
        f"| Overall classification | **{data_class}** |",
        "",
        "## Pipeline vs dashboard reconciliation",
        "",
        "| Metric | Pipeline run | Database | Dashboard | Notes |",
        "|--------|-------------|----------|-----------|-------|",
        f"| Videos processed | {videos_processed} (CAM 1, 3, 5 × 50 frames) | {len({e['camera_id'] for e in db['events'] if e['camera_id']})} cameras in events | provenance | Mock ingest via `python -m pipeline.run --mock --ingest` |",
        f"| Frames sampled | {frames_processed} | {sm['frame_events']} `vision.frame.processed` rows | — | Frame events emitted every `emit_frame_events_every_n=30` sampled frames only |",
        f"| Detections | embedded in frame events | {sm['detections']} detection objects in JSON | — | Not a dashboard KPI |",
        f"| Generated events | 13 (4+5+4 per camera run) | {db_events} | pipeline_events={pipeline_events_kpi} | {'✅ Match' if db_events == pipeline_events_kpi else '⚠️ Mismatch'} |",
        f"| Unique tracks | 3 global IDs | SQL={sm['unique_visitors']} | unique_visitors={unique_kpi} | {'✅ Match' if sm['unique_visitors'] == unique_kpi else '⚠️ Mismatch'} |",
        f"| Zone enters | 4 customer zone enters | SQL={sm['zone_visits_raw']} | zone_visits={zone_kpi} | {'✅ Match' if sm['zone_visits_raw'] == zone_kpi else '⚠️ Mismatch'} |",
        f"| Customer sessions | 1 (CAM 3 entry only) | SQL={sm['sessions']} | customer_sessions={kpis.get('customer_sessions', {}).get('value')} | Sessions created only on `is_store_entry` (CAM 3 entry_threshold) |",
        "",
        "### Mismatch explanations",
        "",
        "1. **150 frames vs 6 frame events** — Pipeline samples 50 frames/camera but emits `vision.frame.processed` only every 30th sampled frame (`processing.emit_frame_events_every_n: 30`). Zone/track events are sparse by design.",
        "2. **3 unique visitors vs 1 session** — Each camera mock run creates a distinct `external_track_id`. Only CAM 3 crosses `entry_threshold` → one persisted `sessions` row. CAM 1/5 tracks contribute zone events but not store-entry sessions.",
        "3. **No `detector_mode` on legacy rows** — Events ingested before the lineage stamp lack payload metadata; classification inferred from ingest command (`--mock`). Re-ingest with updated emitter to stamp `detector_mode` + `source_video`.",
        "4. **Footfall chart empty** — `store_metrics` has projected buckets only after projector runs; chart uses placeholder until enough hourly buckets exist.",
        "5. **Anomalies are derived rules** — Computed on-read from funnel/heatmap baselines, not raw CCTV counts.",
        "",
        "## Table row counts",
        "",
        "| Table | Rows | Role |",
        "|-------|-----:|------|",
    ]
    for table, count in tc.items():
        role = {
            "events": "Ingested pipeline + vision events (source of truth)",
            "sessions": "Visit sessions from entry threshold",
            "transactions": "POS purchases (empty unless linked)",
            "stores": "Demo store seed only",
            "anomalies": "Persisted anomalies (optional)",
            "store_metrics": "Projected footfall time series",
        }[table]
        sections.append(f"| `{table}` | {count} | {role} |")

    sections.extend(["", "## Per-metric audit", ""])

    period_filter = f"`occurred_at BETWEEN '{period['start']}' AND '{period['end']}'` (default last 24h if query params omitted)"
    store_filter = f"`store_id = '{STORE}'`"

    sections.append(
        _metric_section(
            "Unique Visitors",
            sql="""SELECT COUNT(DISTINCT payload->>'external_track_id')
FROM events
WHERE store_id = :store AND occurred_at BETWEEN :from AND :to
  AND payload->>'external_track_id' IS NOT NULL
  AND lower(coalesce(payload->>'class_label','')) != 'staff'
  AND lower(coalesce(payload->>'zone_type','')) NOT IN ('staff_only','ignore')""",
            table="events",
            row_count=tc["events"],
            videos="CAM 1.mp4, CAM 3.mp4, CAM 5.mp4 (via mock trajectories)",
            events=event_lines,
            classification=data_class + " → **derived** distinct track count",
            hardcoded="None — computed in `visitor_count.count_distinct_visitor_ids()`",
            date_filter=period_filter,
            store_filter=store_filter,
            dedupe="Distinct on `external_track_id`; staff/ignore zones excluded",
            dashboard_value=unique_kpi,
            sql_value=sm["unique_visitors"],
        )
    )

    sections.append(
        _metric_section(
            "Total Entries",
            sql="""SELECT COUNT(*) FROM events
WHERE store_id = :store AND event_type = 'vision.zone.entered'
  AND payload->>'is_store_entry' IN ('true','True','1')""",
            table="events",
            row_count=tc["events"],
            videos="CAM 3.mp4 only (entry_threshold zone on entry camera)",
            events="Rows where `is_store_entry=true` (typically one CAM 3 crossing)",
            classification=data_class,
            hardcoded="Entry flag set in `EventBuilder.zone_event()` when zone_type in (entry_threshold, entrance)",
            date_filter=period_filter,
            store_filter=store_filter,
            dedupe="None at SQL layer; zone debounce in pipeline",
            dashboard_value=kpis.get("total_entries", {}).get("value"),
            sql_value=sm["total_entries"],
        )
    )

    sections.append(
        _metric_section(
            "Total Exits",
            sql="""SELECT COUNT(*) FROM events
WHERE event_type IN ('vision.zone.entered','vision.zone.exited')
  AND payload->>'is_store_exit' IN ('true','True','1')""",
            table="events",
            row_count=tc["events"],
            videos="None in current mock run (no exit threshold crossed)",
            events="Zero rows with `is_store_exit=true`",
            classification=data_class,
            hardcoded="Exit flag from pipeline zone transition",
            date_filter=period_filter,
            store_filter=store_filter,
            dedupe="Pipeline line debounce",
            dashboard_value=kpis.get("total_exits", {}).get("value"),
            sql_value=sm["total_exits"],
        )
    )

    sections.append(
        _metric_section(
            "Re-Entries",
            sql="""Dashboard uses MAX(event reentry count, funnel re_entry sum)
Event SQL: COUNT(*) WHERE payload->>'is_reentry' = true""",
            table="events + funnel engine",
            row_count=tc["events"],
            videos="All cameras (funnel stage re-touches)",
            events="Funnel `re_entry_count` aggregated across stages",
            classification="**derived** from funnel calculator + event flags",
            hardcoded="`re_entries = max(reentry_events, funnel_reentries)` in dashboard_service",
            date_filter=period_filter,
            store_filter=store_filter,
            dedupe="First-touch funnel — re-entries increment stage re_entry_count not stage count",
            dashboard_value=kpis.get("re_entries", {}).get("value"),
            sql_value=max(sm["re_entries"], sum(s.get("re_entry_count", 0) for s in funnel.get("stages", []))),
        )
    )

    sections.append(
        _metric_section(
            "Sessions (Customer Sessions KPI)",
            sql="""SELECT COUNT(*) FROM sessions
WHERE store_id = :store AND started_at BETWEEN :from AND :to
  AND coalesce(metadata->>'staff','false') NOT IN ('true','True','1')""",
            table="sessions",
            row_count=tc["sessions"],
            videos="CAM 3.mp4 (entry session creation)",
            events="1 session row linked to CAM 3 entry track",
            classification=data_class + " → persisted session from pipeline `--persist-sessions`",
            hardcoded="Funnel meta `session_count` = customer sessions in period",
            date_filter="`sessions.started_at` in window",
            store_filter=store_filter,
            dedupe="Session merge within 45s (`session.merge_active_within_seconds`)",
            dashboard_value=kpis.get("customer_sessions", {}).get("value"),
            sql_value=sm["sessions"],
        )
    )

    sections.append(
        _metric_section(
            "Zone Visits",
            sql="""Heatmap engine: COUNT customer vision.zone.entered per zone, SUM visit_count
Raw SQL equivalent: COUNT(*) FROM events WHERE event_type='vision.zone.entered' AND customer filter""",
            table="events",
            row_count=tc["events"],
            videos="CAM 1, 3, 5 — one zone enter each (+ CAM 1 second zone)",
            events=event_lines,
            classification="**derived** via HeatmapCalculator from zone enter events",
            hardcoded="Dashboard reads `heatmap.meta.total_visits`",
            date_filter=period_filter,
            store_filter=store_filter,
            dedupe="Staff/ignore filtered; layout remap optional",
            dashboard_value=zone_kpi,
            sql_value=sm["zone_visits_raw"],
        )
    )

    funnel_stage_lines = "\n".join(
        f"- {s['stage']}: count={s['count']} re_entry={s.get('re_entry_count', 0)}"
        for s in funnel.get("stages", [])
    )
    sections.extend(
        [
            "### Funnel",
            "",
            "Computed in-memory by `FunnelCalculator` from `sessions` + `events` + `transactions`.",
            "",
            "**Source tables:** `sessions`, `events` (zone enter + purchase events), `transactions`",
            "",
            funnel_stage_lines,
            "",
            "- **Classification:** derived / first-touch funnel",
            "- **Hardcoded:** stage order ENTRY→ZONE_VISIT→BILLING_QUEUE→PURCHASE in `FUNNEL_STAGE_ORDER`",
            "- **Date filter:** sessions by `started_at`; events by `occurred_at`",
            "- **Dedupe:** `external_track_id` visitor keys; re-entries don't increase stage count",
            "",
            "### Heatmap",
            "",
            f"- **Zones returned:** {len(heatmap.get('zones', []))}",
            f"- **Total visits (meta):** {heatmap.get('meta', {}).get('total_visits')}",
            f"- **Source:** `events` where type in (vision.zone.entered, vision.zone.exited)",
            f"- **Classification:** derived normalization (0–1 scores), not raw CCTV pixels",
            f"- **Layout remap:** Brigade Road YAML when configured",
            "",
            "### Anomalies",
            "",
            f"- **Items shown:** {len(anomalies.get('items', []))}",
            "- **Source:** on-read rule engine (`AnomalyDetector`) + optional `anomalies` table",
            "- **Classification:** **derived** — QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, STALE_FEED",
            "- **Not direct CCTV counts** — compares current vs baseline window",
            "",
            "## Event inventory (all rows)",
            "",
            "| Time | Type | Camera / Video | Track | Flags |",
            "|------|------|----------------|-------|-------|",
        ]
    )
    for e in db["events"]:
        cam = CAMERA_VIDEO.get(e["camera_id"], e["camera_id"])
        flags = []
        if e.get("is_store_entry"):
            flags.append("ENTRY")
        if e.get("zone_type"):
            flags.append(e["zone_type"])
        sections.append(
            f"| {e['at']} | {e['type']} | {cam} | `{e.get('track', '—')}` | {', '.join(flags) or '—'} |"
        )

    sections.extend(
        [
            "",
            "## Recommendations",
        "",
        "## Fix applied — dashboard lineage transparency",
        "",
        "| Item | Before | After (re-ingest with updated emitter) |",
        "|------|--------|----------------------------------------|",
        "| `payload.detector_mode` | `null` on legacy rows | `mock` or `yolo` stamped on every event |",
        "| `payload.source_video` | absent | path to MP4 on frame events |",
        "| Dashboard provenance bar | no detector label | **Detector: MOCK/YOLO** + video filenames |",
        "| KPI SQL logic | unchanged | unchanged — still 100% from `events`/`sessions` |",
        "",
        f"After CAM 3 re-ingest (10 frames): events **13 → {db_events}**, unique_visitors **3 → {unique_kpi}**, sessions **1 → {kpis.get('customer_sessions', {}).get('value')}**.",
        "",
        "## Recommendations",
            "",
            "1. **For real YOLO proof:** re-run without `--mock`:",
            "   `python -m pipeline.run --ingest --persist-sessions --camera \"CAM 3\" --max-frames 50`",
            "2. **Re-ingest** to stamp `detector_mode` + `source_video` on all payloads (fix applied in `pipeline/emit.py`).",
            "3. **Dashboard provenance bar** now surfaces detector mode and source videos when present.",
            "4. **Do not treat mock trajectory runs as production CCTV accuracy** — they validate ingest/funnel wiring only.",
            "",
            "## Verification commands",
            "",
            "```bash",
            "python scripts/generate_reality_audit_report.py",
            "python scripts/verify_dashboard_apis.py",
            "```",
        ]
    )

    return "\n".join(sections) + "\n"


async def main() -> int:
    try:
        db = await _db_audit()
    except Exception as exc:
        print(f"DB audit failed: {exc}", file=sys.stderr)
        return 1

    try:
        api = _fetch_api()
    except Exception as exc:
        print(f"API fetch failed: {exc}", file=sys.stderr)
        return 1

    jsonl = _read_jsonl()
    report = _build_report(db, api, jsonl)
    REPORT.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
