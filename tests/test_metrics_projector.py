# PROMPT:
# Metrics projector and security branch coverage for 96% gate.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings, get_settings
from app.domain.funnel.stages import ZONE_ENTER_EVENT_TYPE
from app.models import Event
from app.repositories.store_metric_repository import StoreMetricRepository
from app.security import UnauthorizedError, api_key_headers, require_api_key
from app.services.metrics_projector_service import MetricsProjectorService
from tests.helpers.constants import DEMO_TENANT_ID


@pytest.mark.asyncio
async def test_metrics_projector_writes_footfall_buckets(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse", "class_label": "visitor"},
                correlation_id="mp1",
                occurred_at=now - timedelta(minutes=10),
            )
        )
        await session.flush()
        projector = MetricsProjectorService(session)
        written = await projector.project_footfall(seeded_store, hours_back=1)
        assert written >= 1
        repo = StoreMetricRepository(session)
        rows = await repo.get_by_store(seeded_store, "footfall.count")
        assert len(rows) >= 1
        await session.commit()


@pytest.mark.asyncio
async def test_metrics_projector_skips_staff_events(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        now = datetime.now(tz=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type=ZONE_ENTER_EVENT_TYPE,
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "staff_only", "class_label": "staff"},
                correlation_id="mp-staff",
                occurred_at=now,
            )
        )
        await session.flush()
        written = await MetricsProjectorService(session).project_footfall(seeded_store, hours_back=1)
        assert written == 0
        await session.commit()


@pytest.mark.asyncio
async def test_ingest_triggers_metrics_projection(
    ingestion_service, seeded_store: uuid.UUID
) -> None:
    from app.schemas.events import EventAggregate, EventIngestRequest

    service, session = ingestion_service
    req = EventIngestRequest(
        event_type=ZONE_ENTER_EVENT_TYPE,
        occurred_at=datetime.now(tz=UTC),
        store_id=seeded_store,
        aggregate=EventAggregate(type="zone", id=uuid.uuid4()),
        payload={"zone_type": "browse", "class_label": "visitor"},
    )
    await service.ingest_batch(
        __import__("app.schemas.events", fromlist=["EventBatchIngestRequest"]).EventBatchIngestRequest(
            events=[req]
        ),
        "metrics-proj",
    )
    repo = StoreMetricRepository(session)
    rows = await repo.get_by_store(seeded_store, "footfall.count")
    assert len(rows) >= 1
    await session.commit()


@pytest.mark.asyncio
async def test_security_require_api_key_branches() -> None:
    get_settings.cache_clear()
    settings = Settings(api_key_required=False)
    await require_api_key(None, settings)

    settings = Settings(api_key_required=True, api_key="", reviewer_mode=False)
    await require_api_key(None, settings)

    settings = Settings(api_key_required=True, api_key="secret", reviewer_mode=False)
    with pytest.raises(UnauthorizedError):
        await require_api_key("wrong", settings)

    await require_api_key("secret", settings)

    settings = Settings(api_key_required=True, api_key="secret", reviewer_mode=True)
    await require_api_key("purple-demo-key", settings)
    with pytest.raises(UnauthorizedError):
        await require_api_key("wrong", settings)

    get_settings.cache_clear()


def test_api_key_headers_helper() -> None:
    get_settings.cache_clear()
    assert api_key_headers(Settings(api_key="abc", reviewer_mode=False)) == {"X-API-Key": "abc"}
    assert api_key_headers(Settings(reviewer_mode=True, api_key="")) == {
        "X-API-Key": "purple-demo-key"
    }
    get_settings.cache_clear()
