# PROMPT:
# Generate complete pytest suite — heatmap zone metrics and anomaly service integration smoke.
#
# CHANGES MADE:
# - Zone activity seed helper tests and stale-feed anomaly on empty database.

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models import Event, VisitSession
from app.repositories.anomaly_repository import AnomalyRepository
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.store_repository import StoreRepository
from app.services.anomaly_service import AnomalyService
from app.services.heatmap_service import HeatmapService


@pytest.fixture
async def heatmap_service(db_session_factory):
    async with db_session_factory() as session:
        yield HeatmapService(
            heatmap_repository=HeatmapRepository(session),
            store_repository=StoreRepository(session),
        ), session


@pytest.fixture
async def anomaly_service(db_session_factory):
    async with db_session_factory() as session:
        yield AnomalyService(
            heatmap_repository=HeatmapRepository(session),
            funnel_repository=FunnelRepository(session),
            store_repository=StoreRepository(session),
            anomaly_repository=AnomalyRepository(session),
            event_repository=EventRepository(session),
        ), session


async def _seed_zone_activity(session, store_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    now = datetime.now(tz=UTC)
    vs = VisitSession(
        store_id=store_id,
        external_track_id="hm-track-1",
        status="completed",
        started_at=now - timedelta(hours=2),
        ended_at=now,
    )
    session.add(vs)
    await session.flush()

    events = [
        Event(
            store_id=store_id,
            tenant_id=tenant_id,
            session_id=vs.id,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={"zone_type": "browse"},
            correlation_id="hm1",
            occurred_at=now - timedelta(hours=1, minutes=50),
        ),
        Event(
            store_id=store_id,
            tenant_id=tenant_id,
            session_id=vs.id,
            event_type="vision.zone.exited",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={"zone_type": "browse", "dwell_ms": 45000},
            correlation_id="hm2",
            occurred_at=now - timedelta(hours=1, minutes=49),
        ),
        Event(
            store_id=store_id,
            tenant_id=tenant_id,
            session_id=vs.id,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={"zone_type": "checkout"},
            correlation_id="hm3",
            occurred_at=now - timedelta(hours=1, minutes=30),
        ),
        Event(
            store_id=store_id,
            tenant_id=tenant_id,
            event_type="vision.frame.processed",
            schema_version="1.0.0",
            aggregate_type="pipeline_run",
            aggregate_id=uuid.uuid4(),
            payload={"frame_index": 1},
            correlation_id="hm4",
            occurred_at=now - timedelta(minutes=5),
        ),
    ]
    for event in events:
        session.add(event)
    await session.flush()


@pytest.mark.asyncio
async def test_heatmap_zone_metrics(heatmap_service, seeded_store: uuid.UUID) -> None:
    service, session = heatmap_service
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    await _seed_zone_activity(session, seeded_store, tenant_id)
    await session.commit()

    result = await service.get_heatmap(seeded_store)
    zones = {z.zone_key: z for z in result.zones}

    assert result.meta["source"] == "heatmap_engine"
    assert result.meta["data_confidence"] in {"LOW", "MEDIUM", "HIGH"}
    assert zones["type:browse"].visit_count == 1
    assert zones["type:browse"].avg_dwell_seconds == 45.0
    assert zones["type:checkout"].visit_count == 1
    assert 0.0 <= zones["type:browse"].normalized_visit_score <= 1.0


@pytest.mark.asyncio
async def test_heatmap_api(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/heatmap")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == str(seeded_store)
    assert "zones" in body
    assert "data_confidence" in body["meta"]


@pytest.mark.asyncio
async def test_anomalies_zone_id_unpacking(
    anomaly_service, seeded_store: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    """Regression: HeatmapService._resolve_zone returns 3-tuple (zone_key, label, camera_zone_id)."""
    service, session = anomaly_service
    now = datetime.now(tz=UTC)
    session.add(
        Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={
                "zone_id": "zone-cam5-checkout",
                "zone_name": "Checkout",
                "zone_type": "billing_queue",
                "class_label": "visitor",
                "external_track_id": "anomaly-zone-id",
            },
            correlation_id="anomaly-zone-id",
            occurred_at=now - timedelta(minutes=5),
        )
    )
    await session.commit()

    result = await service.get_anomalies(seeded_store)
    assert result.store_id == seeded_store
    assert isinstance(result.items, list)


@pytest.mark.asyncio
async def test_anomalies_stale_feed(anomaly_service, seeded_store: uuid.UUID) -> None:
    service, session = anomaly_service
    await session.commit()

    result = await service.get_anomalies(seeded_store)
    types = {item.anomaly_type for item in result.items}
    assert "STALE_FEED" in types
    stale = next(i for i in result.items if i.anomaly_type == "STALE_FEED")
    assert stale.severity == "CRITICAL"
    assert stale.suggested_action


@pytest.mark.asyncio
async def test_anomalies_api(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/anomalies")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == str(seeded_store)
    assert isinstance(body["items"], list)
