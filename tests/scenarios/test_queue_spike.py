# PROMPT:
# Generate complete pytest suite scenario: queue spike anomaly.
# Baseline checkout traffic vs elevated current-period queue visits triggers QUEUE_SPIKE.
#
# CHANGES MADE:
# - Seeds baseline and current windows with realistic checkout enter events.
# - Asserts AnomalyService and API return QUEUE_SPIKE with WARN or CRITICAL severity.

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient

from tests.helpers.seed import seed_checkout_visits, seed_frame_event


@pytest.mark.asyncio
async def test_queue_spike_detected_by_service(
    anomaly_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = anomaly_service
    now = datetime.now(tz=UTC)
    period_end = now
    period_start = now - timedelta(hours=24)
    baseline_start = period_start - timedelta(hours=24)

    await seed_checkout_visits(
        session,
        seeded_store,
        tenant_id=tenant_id,
        count=8,
        window_start=baseline_start + timedelta(hours=1),
        window_end=period_start - timedelta(hours=1),
    )
    await seed_checkout_visits(
        session,
        seeded_store,
        tenant_id=tenant_id,
        count=30,
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
    spike = next((item for item in result.items if item.anomaly_type == "QUEUE_SPIKE"), None)

    assert spike is not None
    assert spike.severity in {"WARN", "CRITICAL"}
    assert spike.suggested_action
    assert spike.context["spike_ratio"] >= 1.5


@pytest.mark.asyncio
async def test_queue_spike_api(client: AsyncClient, db_session_factory, seeded_store: UUID, tenant_id: UUID) -> None:
    now = datetime.now(tz=UTC)
    period_end = now
    period_start = now - timedelta(hours=24)
    baseline_start = period_start - timedelta(hours=24)

    async with db_session_factory() as session:
        await seed_checkout_visits(
            session,
            seeded_store,
            tenant_id=tenant_id,
            count=6,
            window_start=baseline_start + timedelta(hours=2),
            window_end=period_start - timedelta(hours=2),
        )
        await seed_checkout_visits(
            session,
            seeded_store,
            tenant_id=tenant_id,
            count=24,
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
    assert "QUEUE_SPIKE" in types


@pytest.mark.asyncio
async def test_queue_spike_not_triggered_when_stable(
    anomaly_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = anomaly_service
    now = datetime.now(tz=UTC)
    period_end = now
    period_start = now - timedelta(hours=24)
    baseline_start = period_start - timedelta(hours=24)

    for window_start, window_end, count in [
        (baseline_start + timedelta(hours=1), period_start - timedelta(hours=1), 10),
        (period_start + timedelta(hours=1), period_end - timedelta(minutes=5), 11),
    ]:
        await seed_checkout_visits(
            session,
            seeded_store,
            tenant_id=tenant_id,
            count=count,
            window_start=window_start,
            window_end=window_end,
        )
    await seed_frame_event(session, seeded_store, tenant_id=tenant_id, occurred_at=now - timedelta(minutes=1))
    await session.commit()

    result = await service.get_anomalies(seeded_store, from_ts=period_start, to_ts=period_end)
    assert all(item.anomaly_type != "QUEUE_SPIKE" for item in result.items)
