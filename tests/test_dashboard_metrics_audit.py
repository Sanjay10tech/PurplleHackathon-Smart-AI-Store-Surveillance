"""Verify dashboard KPIs match PostgreSQL/SQLite ground truth on pipeline-shaped data."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dashboard.coverage import get_event_coverage
from app.domain.dashboard.kpi_queries import count_pipeline_events
from app.domain.dashboard.period import resolve_analysis_period
from tests.helpers.constants import DEMO_TENANT_ID
from tests.helpers.pipeline_event_seed import seed_pipeline_retail_day


@pytest.mark.asyncio
async def test_dashboard_metrics_audit_matches_database(
    client: AsyncClient,
    db_session_factory,
    seeded_store: uuid.UUID,
) -> None:
    async with db_session_factory() as session:
        await seed_pipeline_retail_day(session, seeded_store, tenant_id=DEMO_TENANT_ID)
        await session.commit()

    summary = (await client.get(f"/api/v1/stores/{seeded_store}/dashboard/summary")).json()
    period_start = summary["period_start"]
    period_end = summary["period_end"]
    params = {"from": period_start, "to": period_end}

    funnel = (await client.get(f"/api/v1/stores/{seeded_store}/funnel", params=params)).json()
    heatmap = (await client.get(f"/api/v1/stores/{seeded_store}/heatmap", params=params)).json()
    anomalies = (await client.get(f"/api/v1/stores/{seeded_store}/anomalies", params=params)).json()

    kpis = {k["key"]: k["value"] for k in summary["kpis"]}
    stages = {s["stage"]: s for s in funnel["stages"]}

    async with db_session_factory() as session:
        ps = datetime.fromisoformat(period_start.replace("Z", "+00:00"))
        pe = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
        db_events = await count_pipeline_events(session, seeded_store, ps, pe)
        coverage = await get_event_coverage(session, seeded_store, ps, pe)

    evidence = summary["reviewer_evidence"]

    assert kpis["unique_visitors"] == funnel["unique_visitors"]
    assert kpis["total_entries"] == stages["ENTRY"]["count"]
    assert kpis["customer_sessions"] == funnel["meta"]["session_count"]
    assert kpis["queue_depth"] == stages["BILLING_QUEUE"]["count"]
    assert kpis["anomalies"] == len(anomalies["items"])
    assert evidence["events_generated"] == db_events
    assert evidence["frames_analyzed"] == coverage["frames_logged"]

    funnel_match = all(
        stages[s["stage"]]["count"] == s["count"] for s in summary["funnel_stages"]
    )
    assert funnel_match

    print("\nREAL DATA VERIFIED\n")
    print(f"  Videos processed:  {evidence['videos_processed']}  ({', '.join(evidence['source_videos']) or 'none'})")
    print(f"  Frames analyzed:   {evidence['frames_analyzed']}")
    print(f"  Events generated:  {evidence['events_generated']}")
    print(f"  Unique visitors:   {kpis['unique_visitors']}")
    print(f"  Funnel counts:     ENTRY={stages['ENTRY']['count']} ZONE={stages['ZONE_VISIT']['count']} "
          f"QUEUE={stages['BILLING_QUEUE']['count']} PURCHASE={stages['PURCHASE']['count']}")
    print(f"  Heatmap visits:    total={heatmap['meta']['total_visits']} zones={len(heatmap['zones'])}")
    print(f"  Anomaly counts:    {len(anomalies['items'])} types={[a['anomaly_type'] for a in anomalies['items']]}")
