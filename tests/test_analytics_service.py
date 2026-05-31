# PROMPT:
# Analytics service validation — store_metrics vs placeholder branches.
#
# CHANGES MADE:
# - Tests footfall series from store_metrics table and placeholder messaging.

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import StoreMetric
from tests.helpers.pipeline_event_seed import seed_pipeline_retail_day
from tests.helpers.seed import seed_frame_event


@pytest.mark.asyncio
async def test_metrics_returns_store_metrics_series(
    analytics_service,
    seeded_store: uuid.UUID,
    tenant_id: uuid.UUID,
) -> None:
    service, session = analytics_service
    await seed_pipeline_retail_day(session, seeded_store, tenant_id=tenant_id)
    await session.commit()

    result = await service.get_metrics(seeded_store)
    assert result.meta.source == "store_metrics"
    assert len(result.series) >= 1
    assert result.series[0].value == 10.0
    assert result.meta.partial is False


@pytest.mark.asyncio
async def test_metrics_placeholder_when_no_events(
    analytics_service,
    seeded_store: uuid.UUID,
) -> None:
    service, _session = analytics_service
    result = await service.get_metrics(seeded_store)
    assert result.meta.source == "placeholder"
    assert result.series == []
    assert "No Data Available" in (result.meta.message or "")
    assert "ingest CCTV" in (result.meta.message or "")


@pytest.mark.asyncio
async def test_metrics_placeholder_with_events_pending_projection(
    analytics_service,
    seeded_store: uuid.UUID,
    tenant_id: uuid.UUID,
) -> None:
    service, session = analytics_service
    await seed_frame_event(
        session,
        seeded_store,
        tenant_id=tenant_id,
        occurred_at=datetime.now(tz=UTC) - timedelta(minutes=5),
    )
    await session.commit()

    result = await service.get_metrics(seeded_store)
    assert result.meta.source == "placeholder"
    assert "vision events in period" in (result.meta.message or "")


@pytest.mark.asyncio
async def test_metrics_respects_query_window(
    analytics_service,
    seeded_store: uuid.UUID,
) -> None:
    service, session = analytics_service
    bucket = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0)
    session.add(
        StoreMetric(
            store_id=seeded_store,
            metric_name="footfall.count",
            bucket_start=bucket - timedelta(days=10),
            bucket_end=bucket - timedelta(days=10, hours=-1),
            granularity="hour",
            dimensions={},
            value=99.0,
            sample_count=99,
        )
    )
    await session.commit()

    result = await service.get_metrics(
        seeded_store,
        from_ts=bucket - timedelta(hours=48),
        to_ts=bucket + timedelta(hours=1),
    )
    assert result.series == []
