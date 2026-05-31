# PROMPT:
# Generate complete pytest suite scenario: all stage events for a full retail visit.
# Cover every vision/analytics event type consumed by funnel, heatmap, and health engines.
#
# CHANGES MADE:
# - Seeds frame.processed, zone enter/exit, purchase transaction, and purchase.completed.
# - Asserts funnel reaches PURCHASE, heatmap has zones with dwell, and feed is fresh.

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient

from tests.helpers.seed import seed_all_stage_events


@pytest.mark.asyncio
async def test_all_stage_events_populates_funnel(
    funnel_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = funnel_service
    await seed_all_stage_events(session, seeded_store, tenant_id=tenant_id)
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {stage.stage: stage for stage in result.stages}

    assert result.unique_visitors == 1
    assert stages["ENTRY"].count == 1
    assert stages["ZONE_VISIT"].count == 1
    assert stages["BILLING_QUEUE"].count == 1
    assert stages["PURCHASE"].count == 1
    assert result.meta["source"] == "funnel_engine"


@pytest.mark.asyncio
async def test_all_stage_events_populates_heatmap(
    heatmap_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = heatmap_service
    await seed_all_stage_events(session, seeded_store, tenant_id=tenant_id)
    await session.commit()

    result = await service.get_heatmap(seeded_store)
    zone_keys = {zone.zone_key for zone in result.zones}

    assert result.meta["source"] == "heatmap_engine"
    assert result.meta["total_visits"] >= 3
    assert any("browse" in key for key in zone_keys)
    assert any("checkout" in key for key in zone_keys)
    assert result.meta["zones_with_dwell"] >= 1


@pytest.mark.asyncio
async def test_all_stage_events_api_endpoints(client: AsyncClient, db_session_factory, seeded_store: UUID, tenant_id: UUID) -> None:
    async with db_session_factory() as session:
        await seed_all_stage_events(session, seeded_store, tenant_id=tenant_id)
        await session.commit()

    funnel = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    heatmap = await client.get(f"/api/v1/stores/{seeded_store}/heatmap")
    anomalies = await client.get(f"/api/v1/stores/{seeded_store}/anomalies")

    assert funnel.status_code == 200
    assert funnel.json()["stages"][-1]["count"] == 1
    assert heatmap.status_code == 200
    assert len(heatmap.json()["zones"]) >= 2
    assert anomalies.status_code == 200
    stale_types = {item["anomaly_type"] for item in anomalies.json()["items"]}
    assert "STALE_FEED" not in stale_types


@pytest.mark.asyncio
async def test_all_stage_events_health_feed_fresh(
    client: AsyncClient,
    db_session_factory,
    seeded_store: UUID,
    tenant_id: UUID,
    mock_db_check: None,
) -> None:
    async with db_session_factory() as session:
        await seed_all_stage_events(session, seeded_store, tenant_id=tenant_id)
        await session.commit()

    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["feed"] == "fresh"
    assert body["stale_feed"] is False
    assert body["last_event_at"] is not None

    last_event = datetime.fromisoformat(body["last_event_at"].replace("Z", "+00:00"))
    assert datetime.now(tz=UTC) - last_event < timedelta(minutes=15)
