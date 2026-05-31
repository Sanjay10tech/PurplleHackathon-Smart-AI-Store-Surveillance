# PROMPT:
# Generate complete pytest suite — funnel service journey, track dedupe, and API smoke.
#
# CHANGES MADE:
# - Full journey with re-entry, external_track_id dedupe, and GET /funnel response shape.

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models import Event, Transaction, VisitSession
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.store_repository import StoreRepository
from app.services.funnel_service import FunnelService


@pytest.fixture
async def funnel_service(db_session_factory):
    async with db_session_factory() as session:
        yield FunnelService(
            funnel_repository=FunnelRepository(session),
            store_repository=StoreRepository(session),
            event_repository=EventRepository(session),
        ), session


async def _seed_journey(
    session,
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    track_id: str = "track-1",
    with_reentry: bool = False,
    with_purchase: bool = True,
) -> VisitSession:
    now = datetime.now(tz=UTC)
    vs = VisitSession(
        id=uuid.uuid4(),
        store_id=store_id,
        external_track_id=track_id,
        status="completed",
        started_at=now - timedelta(hours=1),
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
            payload={"zone_type": "browse", "external_track_id": track_id, "class_label": "visitor"},
            correlation_id="c1",
            occurred_at=now - timedelta(minutes=50),
        ),
        Event(
            store_id=store_id,
            tenant_id=tenant_id,
            session_id=vs.id,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={"zone_type": "checkout", "external_track_id": track_id, "class_label": "visitor"},
            correlation_id="c2",
            occurred_at=now - timedelta(minutes=30),
        ),
    ]
    if with_reentry:
        events.append(
            Event(
                store_id=store_id,
                tenant_id=tenant_id,
                session_id=vs.id,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "browse", "external_track_id": track_id, "class_label": "visitor"},
                correlation_id="c3",
                occurred_at=now - timedelta(minutes=20),
            )
        )
    for e in events:
        session.add(e)

    if with_purchase:
        session.add(
            Transaction(
                store_id=store_id,
                session_id=vs.id,
                external_ref=f"POS-{vs.id.hex[:8]}",
                amount=Decimal("19.99"),
                occurred_at=now - timedelta(minutes=10),
            )
        )
    await session.flush()
    return vs


@pytest.mark.asyncio
async def test_funnel_full_journey(funnel_service, seeded_store: uuid.UUID) -> None:
    service, session = funnel_service
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    await _seed_journey(session, seeded_store, tenant_id, with_reentry=True)
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {s.stage: s for s in result.stages}

    assert result.unique_visitors == 1
    assert stages["ENTRY"].count == 1
    assert stages["ZONE_VISIT"].count == 1
    assert stages["ZONE_VISIT"].re_entry_count == 1
    assert stages["BILLING_QUEUE"].count == 1
    assert stages["PURCHASE"].count == 1
    assert stages["ENTRY"].drop_off_rate == 0.0
    assert stages["BILLING_QUEUE"].conversion_rate == 1.0


@pytest.mark.asyncio
async def test_funnel_dedupes_same_track_two_sessions(
    funnel_service, seeded_store: uuid.UUID
) -> None:
    service, session = funnel_service
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    await _seed_journey(session, seeded_store, tenant_id, track_id="track-dup", with_purchase=False)
    now = datetime.now(tz=UTC)
    session.add(
        VisitSession(
            store_id=seeded_store,
            external_track_id="track-dup",
            status="active",
            started_at=now - timedelta(minutes=30),
        )
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    assert result.unique_visitors == 1
    assert result.dedupe_strategy == "external_track_id"
    assert result.stages[0].count == 1


@pytest.mark.asyncio
async def test_funnel_track_events_without_session(
    funnel_service, seeded_store: uuid.UUID
) -> None:
    """Zone enters with external_track_id but no session_id should populate funnel stages."""
    service, session = funnel_service
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    now = datetime.now(tz=UTC)
    track_id = "track-no-session"

    for zone_type, minutes_ago in (
        ("entry_threshold", 55),
        ("aisle", 45),
        ("billing_queue", 35),
    ):
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=tenant_id,
                session_id=None,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": zone_type,
                    "external_track_id": track_id,
                    "class_label": "visitor",
                },
                correlation_id=f"ns-{zone_type}",
                occurred_at=now - timedelta(minutes=minutes_ago),
            )
        )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {s.stage: s for s in result.stages}

    assert result.unique_visitors == 1
    assert stages["ENTRY"].count == 1
    assert stages["ZONE_VISIT"].count == 1
    assert stages["BILLING_QUEUE"].count == 1
    assert stages["PURCHASE"].count == 0


@pytest.mark.asyncio
async def test_funnel_purchase_without_session_uses_track_metadata(
    funnel_service, seeded_store: uuid.UUID
) -> None:
    service, session = funnel_service
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    now = datetime.now(tz=UTC)
    track_id = "pos-track-1"

    session.add(
        Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            session_id=None,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={
                "zone_type": "entry_threshold",
                "external_track_id": track_id,
                "class_label": "visitor",
            },
            correlation_id="pos-entry",
            occurred_at=now - timedelta(minutes=40),
        )
    )
    session.add(
        Transaction(
            store_id=seeded_store,
            session_id=None,
            external_ref="POS-001",
            amount=Decimal("49.99"),
            occurred_at=now - timedelta(minutes=5),
            metadata_={"external_track_id": track_id},
        )
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {s.stage: s for s in result.stages}
    assert stages["ENTRY"].count == 1
    assert stages["PURCHASE"].count == 1


@pytest.mark.asyncio
async def test_funnel_pos_order_without_track_counts_purchase(
    funnel_service, seeded_store: uuid.UUID
) -> None:
    """Sessionless POS CSV row does not inflate funnel PURCHASE (orphan POS)."""
    service, session = funnel_service
    now = datetime.now(tz=UTC)
    session.add(
        Transaction(
            store_id=seeded_store,
            session_id=None,
            external_ref="ML0426KAP0001321",
            amount=Decimal("1247.98"),
            currency="INR",
            occurred_at=now - timedelta(minutes=5),
            metadata_={"source": "pos_csv", "order_id": "104338647"},
        )
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {s.stage: s for s in result.stages}
    assert stages["PURCHASE"].count == 0
    assert result.meta.get("pos_orphan_purchases", 0) >= 1


@pytest.mark.asyncio
async def test_funnel_browse_skincare_maps_to_zone_visit(
    funnel_service, seeded_store: uuid.UUID
) -> None:
    service, session = funnel_service
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    now = datetime.now(tz=UTC)

    session.add(
        Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            session_id=None,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={
                "zone_type": "browse_skincare",
                "external_track_id": "skincare-track",
                "class_label": "visitor",
            },
            correlation_id="skincare",
            occurred_at=now - timedelta(minutes=30),
        )
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {s.stage: s for s in result.stages}
    assert stages["ZONE_VISIT"].count == 1


@pytest.mark.asyncio
async def test_funnel_api(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == str(seeded_store)
    assert len(body["stages"]) == 4
    assert body["stages"][0]["stage"] == "ENTRY"
