# PROMPT:
# Generate complete pytest suite scenario: stale vision feed detection.
# Missing or aged frame/zone events must surface STALE_FEED in health and anomalies.
#
# CHANGES MADE:
# - Tests health endpoint degraded status, anomaly CRITICAL with no feed, and WARN threshold.
# - Validates suggested_action and minutes_since_feed context fields.

from datetime import UTC, datetime, timedelta
from uuid import UUID
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.repositories.health_repository import HealthRepository
from app.services.health_service import HealthService
from tests.helpers.seed import seed_frame_event


@pytest.mark.asyncio
async def test_stale_feed_anomaly_when_no_events(
    anomaly_service,
    seeded_store: UUID,
) -> None:
    service, session = anomaly_service
    await session.commit()

    result = await service.get_anomalies(seeded_store)
    stale = next(item for item in result.items if item.anomaly_type == "STALE_FEED")

    assert stale.severity == "CRITICAL"
    assert stale.suggested_action
    assert stale.context["last_feed_at"] is None


@pytest.mark.asyncio
async def test_stale_feed_warn_when_feed_aged(
    anomaly_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = anomaly_service
    now = datetime.now(tz=UTC)
    await seed_frame_event(
        session,
        seeded_store,
        tenant_id=tenant_id,
        occurred_at=now - timedelta(minutes=30),
    )
    await session.commit()

    result = await service.get_anomalies(seeded_store)
    stale = next(item for item in result.items if item.anomaly_type == "STALE_FEED")

    assert stale.severity == "WARN"
    assert stale.context["minutes_since_feed"] >= 15


@pytest.mark.asyncio
async def test_stale_feed_not_reported_when_fresh(
    anomaly_service,
    seeded_store: UUID,
    tenant_id: UUID,
) -> None:
    service, session = anomaly_service
    await seed_frame_event(
        session,
        seeded_store,
        tenant_id=tenant_id,
        occurred_at=datetime.now(tz=UTC) - timedelta(minutes=2),
    )
    await session.commit()

    result = await service.get_anomalies(seeded_store)
    assert all(item.anomaly_type != "STALE_FEED" for item in result.items)


@pytest.mark.asyncio
async def test_health_degraded_on_stale_feed(
    client: AsyncClient,
    db_session_factory,
    seeded_store: UUID,
    tenant_id: UUID,
    mock_db_check: None,
) -> None:
    async with db_session_factory() as session:
        await seed_frame_event(
            session,
            seeded_store,
            tenant_id=tenant_id,
            occurred_at=datetime.now(tz=UTC) - timedelta(hours=3),
        )
        await session.commit()

    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["stale_feed"] is True
    assert body["checks"]["feed"] == "stale"
    assert body["feed_stale_minutes"] >= 15


@pytest.mark.asyncio
async def test_health_service_stale_feed_critical_no_events(db_session_factory) -> None:
    async with db_session_factory() as session:
        service = HealthService(
            health_repository=HealthRepository(session),
            settings=Settings(health_stale_feed_minutes=15),
        )
        with patch(
            "app.services.health_service.check_database_connection",
            AsyncMock(return_value=True),
        ):
            body, status_code = await service.get_health()

    assert status_code == 200
    assert body.stale_feed is True
    assert body.checks.feed == "unknown"


@pytest.mark.asyncio
async def test_stale_feed_api(client: AsyncClient, seeded_store: UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/anomalies")
    assert response.status_code == 200
    stale = next(item for item in response.json()["items"] if item["anomaly_type"] == "STALE_FEED")
    assert stale["severity"] == "CRITICAL"
    assert stale["suggested_action"]
