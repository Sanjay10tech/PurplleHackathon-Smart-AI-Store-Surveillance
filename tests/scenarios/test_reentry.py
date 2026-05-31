# PROMPT:
# Generate complete pytest suite scenario: zone re-entry during a single visit.
# Re-entry must increment re_entry_count without inflating first-touch stage counts.
#
# CHANGES MADE:
# - Service and API tests for browse zone re-entry after checkout visit.
# - Validates funnel re_entry_count and stable ZONE_VISIT count of 1.

from uuid import UUID

import pytest
from httpx import AsyncClient

from tests.helpers.seed import seed_visit_session


@pytest.mark.asyncio
async def test_reentry_increments_reentry_count_only(
    funnel_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = funnel_service
    await seed_visit_session(
        session,
        seeded_store,
        tenant_id=tenant_id,
        track_id="reentry-track",
        with_reentry=True,
        with_purchase=True,
        zone_types=["browse", "checkout"],
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {stage.stage: stage for stage in result.stages}

    assert stages["ZONE_VISIT"].count == 1
    assert stages["ZONE_VISIT"].re_entry_count == 1
    assert stages["BILLING_QUEUE"].count == 1
    assert stages["PURCHASE"].count == 1


@pytest.mark.asyncio
async def test_reentry_api_exposes_reentry_count(
    client: AsyncClient,
    db_session_factory,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    async with db_session_factory() as session:
        await seed_visit_session(
            session,
            seeded_store,
            tenant_id=tenant_id,
            track_id="reentry-api",
            with_reentry=True,
            with_purchase=True,
        )
        await session.commit()

    response = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    assert response.status_code == 200
    zone_stage = next(s for s in response.json()["stages"] if s["stage"] == "ZONE_VISIT")
    assert zone_stage["count"] == 1
    assert zone_stage["re_entry_count"] == 1


@pytest.mark.asyncio
async def test_reentry_heatmap_counts_each_enter(
    heatmap_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = heatmap_service
    await seed_visit_session(
        session,
        seeded_store,
        tenant_id=tenant_id,
        with_reentry=True,
        with_zone_exits=True,
        zone_types=["browse", "checkout"],
    )
    await session.commit()

    result = await service.get_heatmap(seeded_store)
    browse_zones = [z for z in result.zones if "browse" in z.zone_label.lower()]
    assert sum(z.visit_count for z in browse_zones) == 2
