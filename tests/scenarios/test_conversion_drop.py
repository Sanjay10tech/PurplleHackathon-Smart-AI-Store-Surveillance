# PROMPT:
# Generate complete pytest suite scenario: conversion drop anomaly.
# Baseline period with strong purchase rate vs current period with zero purchases.
#
# CHANGES MADE:
# - Seeds baseline cohort (12/12 purchases) and current cohort (12/0 purchases).
# - Asserts CONVERSION_DROP anomaly with suggested_action via service and API.

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient

from tests.helpers.seed import seed_conversion_cohort, seed_frame_event


@pytest.mark.asyncio
async def test_conversion_drop_detected_by_service(
    anomaly_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = anomaly_service
    now = datetime.now(tz=UTC)
    period_end = now
    period_start = now - timedelta(hours=24)
    baseline_start = period_start - timedelta(hours=24)

    await seed_conversion_cohort(
        session,
        seeded_store,
        tenant_id=tenant_id,
        entry_count=12,
        purchase_count=12,
        window_start=baseline_start + timedelta(hours=1),
        window_end=period_start - timedelta(hours=1),
    )
    await seed_conversion_cohort(
        session,
        seeded_store,
        tenant_id=tenant_id,
        entry_count=12,
        purchase_count=0,
        window_start=period_start + timedelta(hours=1),
        window_end=period_end - timedelta(minutes=5),
    )
    await seed_frame_event(session, seeded_store, tenant_id=tenant_id, occurred_at=now - timedelta(minutes=2))
    await session.commit()

    result = await service.get_anomalies(
        seeded_store,
        from_ts=period_start,
        to_ts=period_end,
    )
    drop = next((item for item in result.items if item.anomaly_type == "CONVERSION_DROP"), None)

    assert drop is not None
    assert drop.severity in {"WARN", "CRITICAL"}
    assert drop.suggested_action
    assert drop.context["drop_percentage_points"] >= 0.15


@pytest.mark.asyncio
async def test_conversion_drop_api(client: AsyncClient, db_session_factory, seeded_store: UUID, tenant_id: UUID) -> None:
    now = datetime.now(tz=UTC)
    period_end = now
    period_start = now - timedelta(hours=24)
    baseline_start = period_start - timedelta(hours=24)

    async with db_session_factory() as session:
        await seed_conversion_cohort(
            session,
            seeded_store,
            tenant_id=tenant_id,
            entry_count=15,
            purchase_count=15,
            window_start=baseline_start + timedelta(hours=2),
            window_end=period_start - timedelta(hours=2),
        )
        await seed_conversion_cohort(
            session,
            seeded_store,
            tenant_id=tenant_id,
            entry_count=15,
            purchase_count=2,
            window_start=period_start + timedelta(hours=2),
            window_end=period_end - timedelta(minutes=10),
        )
        await seed_frame_event(session, seeded_store, tenant_id=tenant_id, occurred_at=now - timedelta(minutes=1))
        await session.commit()

    response = await client.get(
        f"/api/v1/stores/{seeded_store}/anomalies",
        params={"from": period_start.isoformat(), "to": period_end.isoformat()},
    )
    assert response.status_code == 200
    types = {item["anomaly_type"] for item in response.json()["items"]}
    assert "CONVERSION_DROP" in types


@pytest.mark.asyncio
async def test_conversion_drop_not_triggered_when_stable(
    anomaly_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = anomaly_service
    now = datetime.now(tz=UTC)
    period_end = now
    period_start = now - timedelta(hours=24)
    baseline_start = period_start - timedelta(hours=24)

    for window_start, window_end in [
        (baseline_start + timedelta(hours=1), period_start - timedelta(hours=1)),
        (period_start + timedelta(hours=1), period_end - timedelta(minutes=5)),
    ]:
        await seed_conversion_cohort(
            session,
            seeded_store,
            tenant_id=tenant_id,
            entry_count=12,
            purchase_count=8,
            window_start=window_start,
            window_end=window_end,
        )
    await seed_frame_event(session, seeded_store, tenant_id=tenant_id, occurred_at=now - timedelta(minutes=1))
    await session.commit()

    result = await service.get_anomalies(seeded_store, from_ts=period_start, to_ts=period_end)
    assert all(item.anomaly_type != "CONVERSION_DROP" for item in result.items)
