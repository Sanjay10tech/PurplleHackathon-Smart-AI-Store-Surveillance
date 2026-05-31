#!/usr/bin/env python3
"""Compare DB events vs dashboard-visible counts."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx

STORE = UUID("00000000-0000-0000-0000-000000000101")
API = os.environ.get("AUDIT_API_BASE", "http://localhost:8000")
KEY = os.environ.get("API_KEY", "purple-demo-key")


async def db_stats() -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://si:si@localhost:5432/store_intelligence"
    )
    engine = create_async_engine(url)
    Session = async_sessionmaker(engine)
    end = datetime.now(tz=UTC)
    start = end - timedelta(hours=24)

    async with Session() as s:
        p = {"sid": STORE, "a": start, "b": end}
        total = (await s.execute(text("SELECT COUNT(*) FROM events WHERE store_id=:sid"), p)).scalar()
        in_period = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM events WHERE store_id=:sid "
                    "AND occurred_at>=:a AND occurred_at<=:b"
                ),
                p,
            )
        ).scalar()
        outside = total - in_period
        by_type = dict(
            (await s.execute(
                text("SELECT event_type,COUNT(*) FROM events WHERE store_id=:sid GROUP BY 1"),
                p,
            )).all()
        )
        tracks_event_level = (
            await s.execute(
                text(
                    "SELECT COUNT(DISTINCT payload->>'external_track_id') FROM events "
                    "WHERE store_id=:sid AND payload->>'external_track_id' IS NOT NULL "
                    "AND payload->>'external_track_id' != ''"
                ),
                p,
            )
        ).scalar()
        tracks_ended = (
            await s.execute(
                text(
                    "SELECT COUNT(DISTINCT payload->>'external_track_id') FROM events "
                    "WHERE store_id=:sid AND event_type='vision.track.ended'"
                ),
                p,
            )
        ).scalar()
        cameras = (
            await s.execute(
                text(
                    "SELECT payload->>'camera_id', COUNT(*) FROM events "
                    "WHERE store_id=:sid GROUP BY 1"
                ),
                p,
            )
        ).all()
        videos = (
            await s.execute(
                text(
                    "SELECT DISTINCT payload->>'source_video' FROM events "
                    "WHERE store_id=:sid AND payload->>'source_video' IS NOT NULL"
                ),
                p,
            )
        ).all()
    await engine.dispose()
    return {
        "total_events_db": total,
        "events_in_24h_window": in_period,
        "events_outside_window": outside,
        "by_type": by_type,
        "distinct_tracks_on_events": tracks_event_level,
        "distinct_tracks_from_track_ended": tracks_ended,
        "cameras": cameras,
        "source_videos": [v[0] for v in videos if v[0]],
        "window": {"start": start.isoformat(), "end": end.isoformat()},
    }


def api_stats() -> dict:
    headers = {"X-API-Key": KEY}
    with httpx.Client(base_url=API, headers=headers, timeout=30) as c:
        summary = c.get(f"/api/v1/stores/{STORE}/dashboard/summary").json()
        funnel = c.get(f"/api/v1/stores/{STORE}/funnel").json()
        heatmap = c.get(f"/api/v1/stores/{STORE}/heatmap").json()
        metrics = c.get(f"/api/v1/stores/{STORE}/metrics").json()
    kpis = {k["key"]: k["value"] for k in summary.get("kpis", [])}
    return {
        "kpis": kpis,
        "pipeline_events_kpi": kpis.get("pipeline_events"),
        "unique_visitors_kpi": kpis.get("unique_visitors"),
        "zone_visits_kpi": kpis.get("zone_visits"),
        "sessions_kpi": kpis.get("customer_sessions"),
        "period_start": summary.get("period_start"),
        "period_end": summary.get("period_end"),
        "provenance": summary.get("provenance"),
        "funnel_unique": funnel.get("unique_visitors"),
        "funnel_entry": next((s["count"] for s in funnel.get("stages", []) if s["stage"] == "ENTRY"), 0),
        "heatmap_total": heatmap.get("meta", {}).get("total_visits"),
        "metrics_series_points": len(metrics.get("series", [])),
        "metrics_unique": metrics.get("unique_visitors"),
    }


async def main() -> int:
    db = await db_stats()
    api = api_stats()
    missing = db["total_events_db"] - (api["pipeline_events_kpi"] or 0)
    out = {"database": db, "dashboard": api, "missing_events": missing}
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
