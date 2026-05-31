# Linked retail journey tests — POS ↔ CCTV funnel integration.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.domain.funnel.pos_linker import (
    BillingTrackCandidate,
    PosLinkMode,
    PosTransactionCandidate,
    link_billing_to_pos,
)
from app.models import Event, Transaction, VisitSession


@pytest.mark.asyncio
async def test_pos_linker_sequential_match() -> None:
    billing = [
        BillingTrackCandidate("track-a", datetime(2026, 4, 10, 20, 10, tzinfo=UTC)),
        BillingTrackCandidate("track-b", datetime(2026, 4, 10, 20, 15, tzinfo=UTC)),
    ]
    pos = [
        PosTransactionCandidate("tx1", "o1", "INV1", datetime(2026, 4, 10, 12, 0, tzinfo=UTC), "100"),
        PosTransactionCandidate("tx2", "o2", "INV2", datetime(2026, 4, 10, 13, 0, tzinfo=UTC), "200"),
    ]
    matches = link_billing_to_pos(billing, pos, mode=PosLinkMode.SEQUENTIAL)
    assert len(matches) == 2
    assert matches[0].external_track_id == "track-a"
    assert matches[0].invoice_number == "INV1"


@pytest.mark.asyncio
async def test_funnel_linked_pos_purchase_counts_on_track(
    funnel_service, seeded_store: uuid.UUID
) -> None:
    service, session = funnel_service
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    track_id = "journey-track-1"
    now = datetime.now(tz=UTC)

    vs = VisitSession(
        store_id=seeded_store,
        external_track_id=track_id,
        status="completed",
        started_at=now - timedelta(hours=1),
    )
    session.add(vs)
    await session.flush()

    session.add(
        Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            session_id=vs.id,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={"zone_type": "browse", "external_track_id": track_id, "class_label": "visitor"},
            correlation_id="j1",
            occurred_at=now - timedelta(minutes=40),
        )
    )
    session.add(
        Event(
            store_id=seeded_store,
            tenant_id=tenant_id,
            session_id=vs.id,
            event_type="vision.zone.entered",
            schema_version="1.0.0",
            aggregate_type="zone",
            aggregate_id=uuid.uuid4(),
            payload={"zone_type": "checkout", "external_track_id": track_id, "class_label": "visitor"},
            correlation_id="j2",
            occurred_at=now - timedelta(minutes=20),
        )
    )
    session.add(
        Transaction(
            store_id=seeded_store,
            session_id=None,
            external_ref="INV-JOURNEY-1",
            amount=Decimal("499.00"),
            occurred_at=now - timedelta(minutes=10),
            metadata_={
                "source": "pos_csv",
                "order_id": "999001",
                "external_track_id": track_id,
                "journey_link": {"method": "sequential", "confidence": 0.75},
            },
        )
    )
    await session.commit()

    funnel = await service.get_funnel(seeded_store)
    journeys = await service.get_retail_journeys(seeded_store)
    stages = {s.stage: s for s in funnel.stages}

    assert stages["BILLING_QUEUE"].count >= 1
    assert stages["PURCHASE"].count >= 1
    complete = [j for j in journeys.journeys if j.complete]
    assert len(complete) >= 1
    assert complete[0].purchase is not None
    assert complete[0].purchase.invoice_number == "INV-JOURNEY-1"


@pytest.mark.asyncio
async def test_retail_journeys_api(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/funnel/journeys")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == str(seeded_store)
    assert "journeys" in body
    assert "linked_purchases" in body["meta"]
