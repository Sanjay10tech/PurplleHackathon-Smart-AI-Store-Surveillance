from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models import Event, Transaction, VisitSession
from tests.helpers.constants import DEMO_TENANT_ID


@pytest.mark.asyncio
async def test_dashboard_summary_returns_kpis(
    client: AsyncClient,
    db_session_factory,
    seeded_store: uuid.UUID,
) -> None:
    async with db_session_factory() as session:
        now = datetime.now(tz=UTC)
        vs = VisitSession(
            store_id=seeded_store,
            external_track_id="dash-track",
            status="completed",
            started_at=now - timedelta(hours=2),
        )
        session.add(vs)
        await session.flush()
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                session_id=vs.id,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "entry_threshold",
                    "external_track_id": "dash-track",
                    "class_label": "visitor",
                    "is_store_entry": True,
                },
                correlation_id="dash-entry",
                occurred_at=now - timedelta(hours=1),
            )
        )
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "browse",
                    "external_track_id": "dash-track",
                    "class_label": "staff",
                },
                correlation_id="dash-staff",
                occurred_at=now - timedelta(minutes=30),
            )
        )
        session.add(
            Transaction(
                store_id=seeded_store,
                session_id=vs.id,
                external_ref="POS-DASH",
                amount=Decimal("1299.00"),
                currency="INR",
                occurred_at=now - timedelta(minutes=20),
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/stores/{seeded_store}/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    keys = {kpi["key"] for kpi in body["kpis"]}
    assert "unique_visitors" in keys
    assert "total_entries" in keys
    assert "total_exits" in keys
    assert "re_entries" in keys
    assert "customer_sessions" in keys
    assert "conversion_rate" in keys
    assert "revenue" in keys
    assert "purchases" in keys
    assert "average_basket_value" in keys
    assert "queue_depth" in keys
    assert "anomalies" in keys
    assert len(body["kpis"]) == 11
    assert "reviewer_evidence" in body
    assert body["reviewer_evidence"]["events_generated"] >= 1
    assert body["provenance"]["dedupe_strategy"]
    assert body["refresh_interval_seconds"] == 5
