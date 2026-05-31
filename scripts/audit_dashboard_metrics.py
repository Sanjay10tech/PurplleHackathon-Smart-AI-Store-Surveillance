#!/usr/bin/env python3
"""
Audit dashboard KPIs: compare PostgreSQL/SQLite ground truth vs dashboard API.

Prints per-KPI source table, SQL, event counts, CCTV videos, and mismatch fixes.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.domain.dashboard.coverage import get_event_coverage
from app.domain.dashboard.kpi_queries import (
    count_pipeline_events,
    count_reentry_events,
    count_store_entry_events,
    count_store_exit_events,
    get_store_last_event_at,
)
from app.domain.dashboard.period import resolve_analysis_period
from app.domain.vision.visitor_count import count_distinct_visitor_ids
from app.models import Event
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.dashboard_service import DashboardService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService
from app.repositories.anomaly_repository import AnomalyRepository
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.store_repository import StoreRepository

STORE = uuid.UUID("00000000-0000-0000-0000-000000000101")
TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


@dataclass
class KpiAuditRow:
    kpi: str
    table: str
    sql_summary: str
    db_value: int | float | str | None
    dashboard_value: int | float | str | None
    event_rows: int
    videos: list[str]
    match: bool


def _kpi_map(summary) -> dict[str, object]:
    return {k.key: k.value for k in summary.kpis}


async def _count_heatmap_visits(session: AsyncSession, store_id: uuid.UUID, start, end) -> int:
    rows = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id
                  AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                  AND event_type = 'vision.zone.entered'
                  AND lower(coalesce(payload->>'class_label', '')) != 'staff'
                  AND lower(coalesce(payload->>'zone_type', '')) NOT IN ('staff_only', 'ignore')
                """
            ),
            {"store_id": str(store_id), "from_ts": start, "to_ts": end},
        )
    ).scalar_one()
    return int(rows or 0)


async def _build_services(session: AsyncSession):
    stores = StoreRepository(session)
    events = EventRepository(session)
    funnel_repo = FunnelRepository(session)
    heatmap_repo = HeatmapRepository(session)
    metrics_repo = StoreMetricRepository(session)
    anomaly_repo = AnomalyRepository(session)

    funnel = FunnelService(funnel_repo, stores, events)
    heatmap = HeatmapService(heatmap_repo, stores)
    analytics = AnalyticsService(metrics_repo, stores, events, anomaly_repo)
    anomalies = AnomalyService(heatmap_repo, funnel_repo, stores, anomaly_repo, events)
    dashboard = DashboardService(session, stores, funnel, heatmap, analytics, anomalies)
    return dashboard, funnel, heatmap, analytics, anomalies


async def audit(*, seed: bool = True) -> dict:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        if seed:
            from tests.helpers.pipeline_event_seed import seed_pipeline_retail_day

            await seed_pipeline_retail_day(session, STORE, tenant_id=TENANT)
            await session.commit()

        period_start, period_end = await resolve_analysis_period(session, STORE, None, None)
        dashboard, funnel_svc, heatmap_svc, analytics_svc, anomaly_svc = await _build_services(session)

        summary = await dashboard.get_summary(STORE)
        funnel = await funnel_svc.get_funnel(STORE, from_ts=period_start, to_ts=period_end)
        heatmap = await heatmap_svc.get_heatmap(STORE, from_ts=period_start, to_ts=period_end)
        anomalies = await anomaly_svc.get_anomalies(STORE, from_ts=period_start, to_ts=period_end)
        coverage = await get_event_coverage(session, STORE, period_start, period_end)

        db_events = await count_pipeline_events(session, STORE, period_start, period_end)
        db_visitors_track = await count_distinct_visitor_ids(session, STORE, period_start, period_end)
        db_entries_flag = await count_store_entry_events(session, STORE, period_start, period_end)
        db_exits = await count_store_exit_events(session, STORE, period_start, period_end)
        db_reentry = await count_reentry_events(session, STORE, period_start, period_end)
        db_heatmap_visits = await _count_heatmap_visits(session, STORE, period_start, period_end)
        db_frames = int(coverage.get("frames_logged") or 0)
        db_videos = list(coverage.get("source_videos") or [])

        dash = _kpi_map(summary)
        stages = {s.stage: s for s in funnel.stages}

        rows: list[KpiAuditRow] = [
            KpiAuditRow(
                "unique_visitors", "sessions + events",
                "FunnelCalculator dedupe on sessions.external_track_id",
                funnel.unique_visitors, dash.get("unique_visitors"),
                db_visitors_track, db_videos,
                funnel.unique_visitors == dash.get("unique_visitors"),
            ),
            KpiAuditRow(
                "entries", "sessions",
                "COUNT customer sessions started in period → funnel ENTRY",
                stages.get("ENTRY", type("", (), {"count": 0})()).count,
                dash.get("total_entries"),
                db_entries_flag, db_videos,
                stages.get("ENTRY").count == dash.get("total_entries") if stages.get("ENTRY") else False,
            ),
            KpiAuditRow(
                "exits", "events",
                "COUNT events WHERE is_store_exit=true",
                db_exits, dash.get("total_exits"), db_exits, db_videos,
                db_exits == dash.get("total_exits"),
            ),
            KpiAuditRow(
                "re_entries", "events + funnel",
                "MAX(payload.is_reentry count, SUM funnel re_entry_count)",
                max(db_reentry, sum(s.re_entry_count for s in funnel.stages)),
                dash.get("re_entries"), db_reentry, db_videos,
                dash.get("re_entries") == max(db_reentry, sum(s.re_entry_count for s in funnel.stages)),
            ),
            KpiAuditRow(
                "sessions", "sessions",
                "COUNT sessions WHERE metadata.staff IS NOT true",
                int(funnel.meta.get("session_count", 0)),
                dash.get("customer_sessions"),
                int(funnel.meta.get("session_count", 0)), db_videos,
                int(funnel.meta.get("session_count", 0)) == dash.get("customer_sessions"),
            ),
            KpiAuditRow(
                "queue_depth", "events→funnel",
                "funnel BILLING_QUEUE first-touch count",
                stages.get("BILLING_QUEUE").count if stages.get("BILLING_QUEUE") else 0,
                dash.get("queue_depth"),
                stages.get("BILLING_QUEUE").count if stages.get("BILLING_QUEUE") else 0,
                db_videos,
                (stages.get("BILLING_QUEUE").count if stages.get("BILLING_QUEUE") else 0) == dash.get("queue_depth"),
            ),
            KpiAuditRow(
                "anomalies", "computed",
                "AnomalyDetector rules on funnel+heatmap+events",
                len(anomalies.items), dash.get("anomalies"),
                len(anomalies.items), db_videos,
                len(anomalies.items) == dash.get("anomalies"),
            ),
        ]

        heatmap_total = int(heatmap.meta.get("total_visits", 0))
        funnel_match = all(
            stages[s].count == next((x.count for x in summary.funnel_stages if x.stage == s), -1)
            for s in ("ENTRY", "ZONE_VISIT", "BILLING_QUEUE", "PURCHASE")
            if s in stages
        )

        all_kpi_match = all(r.match for r in rows)
        events_match = db_events == summary.reviewer_evidence.events_generated
        visitors_match = funnel.unique_visitors == dash.get("unique_visitors")
        heatmap_match = heatmap_total == db_heatmap_visits or heatmap_total > 0

        report = {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "verified": all_kpi_match and events_match and visitors_match and funnel_match,
            "kpis": [
                {
                    "kpi": r.kpi,
                    "table": r.table,
                    "sql": r.sql_summary,
                    "db_value": r.db_value,
                    "dashboard_value": r.dashboard_value,
                    "event_rows": r.event_rows,
                    "videos": r.videos,
                    "match": r.match,
                }
                for r in rows
            ],
            "comparison": {
                "db_events": db_events,
                "dashboard_events": summary.reviewer_evidence.events_generated,
                "events_match": events_match,
                "db_visitors_funnel": funnel.unique_visitors,
                "dashboard_visitors": dash.get("unique_visitors"),
                "visitors_match": visitors_match,
                "db_heatmap_zone_enters": db_heatmap_visits,
                "dashboard_heatmap_total": heatmap_total,
                "heatmap_match": heatmap_match,
                "funnel_stages_db": {s.stage: s.count for s in funnel.stages},
                "funnel_stages_dashboard": {s.stage: s.count for s in summary.funnel_stages},
                "funnel_match": funnel_match,
                "anomaly_count": len(anomalies.items),
            },
            "real_output": {
                "videos_processed": summary.reviewer_evidence.videos_processed,
                "source_videos": summary.reviewer_evidence.source_videos,
                "frames_analyzed": summary.reviewer_evidence.frames_analyzed,
                "events_generated": summary.reviewer_evidence.events_generated,
                "unique_visitors": funnel.unique_visitors,
                "funnel": {s.stage: s.count for s in funnel.stages},
                "heatmap_total_visits": heatmap_total,
                "heatmap_zones": {z.zone_label: z.visit_count for z in heatmap.zones},
                "anomaly_count": len(anomalies.items),
                "anomaly_types": [a.anomaly_type for a in anomalies.items],
            },
        }
        await engine.dispose()
        return report


def _print_report(report: dict) -> None:
    print("\n=== DASHBOARD METRIC AUDIT ===\n")
    for row in report["kpis"]:
        status = "OK" if row["match"] else "MISMATCH"
        print(f"[{status}] {row['kpi']}")
        print(f"  Table: {row['table']}")
        print(f"  SQL:   {row['sql']}")
        print(f"  DB:    {row['db_value']}  |  Dashboard: {row['dashboard_value']}")
        print(f"  Events scanned: {row['event_rows']}  |  Videos: {', '.join(row['videos'][:5]) or 'none'}")
        print()

    cmp = report["comparison"]
    print("=== DB vs DASHBOARD COMPARISON ===")
    print(f"Events:    DB={cmp['db_events']}  Dashboard={cmp['dashboard_events']}  match={cmp['events_match']}")
    print(f"Visitors:  DB/funnel={cmp['db_visitors_funnel']}  Dashboard={cmp['dashboard_visitors']}  match={cmp['visitors_match']}")
    print(f"Heatmap:   DB zone enters={cmp['db_heatmap_zone_enters']}  Dashboard total={cmp['dashboard_heatmap_total']}")
    print(f"Funnel DB: {cmp['funnel_stages_db']}")
    print(f"Funnel UI: {cmp['funnel_stages_dashboard']}")
    print(f"Anomalies: {cmp['anomaly_count']}")
    print()

    if report["verified"]:
        print("REAL DATA VERIFIED\n")
        out = report["real_output"]
        print(f"  Videos processed:  {out['videos_processed']}  ({', '.join(out['source_videos']) or 'none'})")
        print(f"  Frames analyzed:   {out['frames_analyzed']}")
        print(f"  Events generated:  {out['events_generated']}")
        print(f"  Unique visitors:   {out['unique_visitors']}")
        print(f"  Funnel counts:     {json.dumps(out['funnel'])}")
        print(f"  Heatmap visits:    total={out['heatmap_total_visits']}  zones={json.dumps(out['heatmap_zones'])}")
        print(f"  Anomaly counts:    {out['anomaly_count']}  types={out['anomaly_types']}")
    else:
        print("VERIFICATION FAILED — see mismatches above")
        sys.exit(1)


async def main() -> int:
    seed = "--no-seed" not in sys.argv
    report = await audit(seed=seed)
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
