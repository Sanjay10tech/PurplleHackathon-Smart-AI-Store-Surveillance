"""Tests for POS CSV ingestion and funnel integration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.pos.csv_parser import parse_pos_csv
from app.models import Event, Transaction
from app.services.pos_ingestion_service import PosIngestionService
from tests.helpers.constants import DEMO_TENANT_ID

POS_CSV = Path(__file__).resolve().parents[1] / "data" / "pos" / "Brigade_Bangalore_10_April_26.csv"
STORE = uuid.UUID("00000000-0000-0000-0000-000000000101")


@pytest.mark.skipif(not POS_CSV.is_file(), reason="POS CSV not present")
def test_parse_pos_csv_real_file() -> None:
    orders, analysis = parse_pos_csv(POS_CSV)
    assert analysis.line_count > 50
    assert len(analysis.all_columns) >= 30
    assert len(orders) >= 20
    assert orders[0].nmv > 0
    assert orders[0].brand_totals


@pytest.mark.asyncio
@pytest.mark.skipif(not POS_CSV.is_file(), reason="POS CSV not present")
async def test_pos_ingestion_creates_transactions_and_purchase_events(
    db_session_factory,
    seeded_store: uuid.UUID,
) -> None:
    async with db_session_factory() as session:
        service = PosIngestionService(session)
        result = await service.ingest_store_pos(
            seeded_store,
            csv_path=POS_CSV,
            replace_existing=True,
            link_journeys=False,
            emit_purchase_events=True,
        )
        assert result.orders_parsed >= 20
        assert result.transactions_inserted >= 20
        assert result.purchase_events_created >= 20
        assert result.revenue_nmv > 0


@pytest.mark.asyncio
async def test_funnel_purchase_from_pos_csv_metadata(
    funnel_service,
    seeded_store: uuid.UUID,
) -> None:
    """POS order without CCTV track appears in dashboard KPIs, not funnel PURCHASE."""
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
            metadata_={
                "source": "pos_csv",
                "source_file": "Brigade_Bangalore_10_April_26.csv",
                "order_id": "104338647",
                "brands": [{"brand_name": "Faces Canada", "nmv": "1247.98"}],
                "categories": [{"category": "makeup/Lipstick", "nmv": "614.54"}],
            },
        )
    )
    session.add(
        Event(
            store_id=seeded_store,
            tenant_id=DEMO_TENANT_ID,
            event_type="analytics.purchase.completed",
            schema_version="1.0.0",
            aggregate_type="purchase",
            aggregate_id=uuid.uuid4(),
            payload={
                "funnel_stage": "PURCHASE",
                "order_id": "104338647",
                "source": "pos_csv",
            },
            correlation_id="pos-test",
            idempotency_key="pos-purchase-104338647",
            occurred_at=now - timedelta(minutes=5),
        )
    )
    await session.commit()

    result = await service.get_funnel(seeded_store)
    stages = {s.stage: s for s in result.stages}
    assert stages["PURCHASE"].count == 0
    assert result.meta.get("pos_orphan_purchases", 0) >= 1


@pytest.mark.asyncio
async def test_dashboard_includes_pos_kpis(
    client,
    db_session_factory,
    seeded_store: uuid.UUID,
) -> None:
    async with db_session_factory() as session:
        session.add(
            Transaction(
                store_id=seeded_store,
                external_ref="ML0426KAP0001358",
                amount=Decimal("274.36"),
                currency="INR",
                status="completed",
                occurred_at=datetime(2026, 4, 10, 16, 55, 36, tzinfo=UTC),
                metadata_={
                    "source": "pos_csv",
                    "order_id": "104363838",
                    "brands": [{"brand_name": "DERMDOC", "nmv": "274.36"}],
                    "categories": [{"category": "bath-and-body/Body Wash", "nmv": "274.36"}],
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/stores/{seeded_store}/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    keys = {k["key"] for k in body["kpis"]}
    assert "revenue" in keys
    assert "purchases" in keys
    assert "average_basket_value" in keys
    assert body["pos_insights"] is not None
    assert body["pos_insights"]["purchase_count"] >= 1
