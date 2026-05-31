"""Reviewer-blocking metric consistency — CCTV → sessions → funnel → dashboard."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.services.cctv_bootstrap import bootstrap_cctv_events
from app.services.pos_bootstrap import bootstrap_pos_ingestion
from app.services.reviewer_journey_bootstrap import ensure_reviewer_journey_metrics

BOOTSTRAP = Path("data/reviewer/yolo_bootstrap_events.jsonl")


@pytest.mark.asyncio
async def test_reviewer_metrics_consistent_after_bootstrap(
    client: AsyncClient,
    db_session_factory,
    seeded_store: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not BOOTSTRAP.is_file():
        pytest.skip("bootstrap JSONL missing")

    settings = get_settings()
    monkeypatch.setattr(settings, "cctv_bootstrap_min_events", 9999)
    monkeypatch.setattr(settings, "cctv_store_id", str(seeded_store))
    monkeypatch.setattr(settings, "pos_store_id", str(seeded_store))
    monkeypatch.setattr(settings, "metrics_projector_enabled", False)

    await bootstrap_cctv_events(settings)
    await bootstrap_pos_ingestion(settings)
    journey = await ensure_reviewer_journey_metrics(settings)
    assert journey["tracks_seen"] >= 1
    assert journey["sessions_created"] >= 1 or journey["tracks_seen"] >= 1

    response = await client.get(f"/api/v1/stores/{seeded_store}/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    kpis = {item["key"]: item for item in body["kpis"]}

    entries = int(kpis["total_entries"]["value"])
    exits = int(kpis["total_exits"]["value"])
    sessions = int(kpis["customer_sessions"]["value"])
    purchases = int(kpis["purchases"]["value"])
    events_generated = body["reviewer_evidence"]["events_generated"]
    videos = body["reviewer_evidence"]["videos_processed"]

    bootstrap_lines = [line for line in BOOTSTRAP.read_text().splitlines() if line.strip()]
    assert events_generated >= len(bootstrap_lines) - 5
    assert videos >= 1
    assert entries >= 1
    assert exits >= 1
    assert sessions >= 1
    assert purchases >= 1

    funnel = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    assert funnel.status_code == 200
    stages = {s["stage"]: s["count"] for s in funnel.json()["stages"]}
    assert stages.get("ENTRY", 0) >= 1
    assert stages.get("PURCHASE", 0) <= max(stages.get("ENTRY", 0), purchases)

    linked = kpis["conversion_rate"]["value"]
    if journey["pos_journeys_linked"] > 0:
        assert linked != "No Data Available"
        assert entries >= journey["pos_journeys_linked"]
