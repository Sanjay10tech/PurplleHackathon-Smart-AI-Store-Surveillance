# PROMPT:
# Generate complete pytest suite scenario: zero purchases in the funnel period.
# Visitors reach billing queue but never convert; assert PURCHASE count is zero.
#
# CHANGES MADE:
# - Seeds browse + checkout journeys without transactions or purchase events.
# - Validates funnel drop-off at PURCHASE and billing-to-purchase conversion of 0.

from uuid import UUID

import pytest
from httpx import AsyncClient

from tests.helpers.seed import seed_conversion_cohort, seed_visit_session


@pytest.mark.asyncio
async def test_zero_purchases_funnel_counts(
    funnel_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = funnel_service
    for index in range(5):
        await seed_visit_session(
            session,
            seeded_store,
            tenant_id=tenant_id,
            track_id=f"no-purchase-{index}",
            with_purchase=False,
            zone_types=["browse", "checkout"],
        )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {stage.stage: stage for stage in result.stages}

    assert result.unique_visitors == 5
    assert stages["BILLING_QUEUE"].count == 5
    assert stages["PURCHASE"].count == 0
    assert stages["BILLING_QUEUE"].conversion_rate == 0.0
    assert stages["BILLING_QUEUE"].drop_off_rate == 1.0


@pytest.mark.asyncio
async def test_zero_purchases_api(client: AsyncClient, db_session_factory, seeded_store: UUID, tenant_id: UUID) -> None:
    async with db_session_factory() as session:
        await seed_visit_session(
            session,
            seeded_store,
            tenant_id=tenant_id,
            track_id="zero-purchase-api",
            with_purchase=False,
        )
        await session.commit()

    response = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    assert response.status_code == 200
    purchase = next(s for s in response.json()["stages"] if s["stage"] == "PURCHASE")
    assert purchase["count"] == 0


@pytest.mark.asyncio
async def test_zero_purchases_cohort_conversion_rate(
    funnel_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = funnel_service
    from datetime import UTC, datetime, timedelta

    now = datetime.now(tz=UTC)
    await seed_conversion_cohort(
        session,
        seeded_store,
        tenant_id=tenant_id,
        entry_count=12,
        purchase_count=0,
        window_start=now - timedelta(hours=20),
        window_end=now - timedelta(hours=1),
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {stage.stage: stage for stage in result.stages}
    assert stages["ENTRY"].count == 12
    assert stages["PURCHASE"].count == 0
