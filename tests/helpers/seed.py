"""Realistic retail event/session seed helpers for integration tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Transaction, VisitSession
from tests.helpers.constants import DEMO_TENANT_ID

NOW = lambda: datetime.now(tz=UTC)


def _spread_times(count: int, start: datetime, end: datetime) -> list[datetime]:
    if count <= 0:
        return []
    if count == 1:
        return [start + (end - start) / 2]
    span = (end - start).total_seconds()
    return [start + timedelta(seconds=span * i / (count - 1)) for i in range(count)]


async def seed_visit_session(
    session: AsyncSession,
    store_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID = DEMO_TENANT_ID,
    track_id: str | None = None,
    started_at: datetime | None = None,
    with_purchase: bool = False,
    purchase_amount: Decimal = Decimal("24.99"),
    zone_types: list[str] | None = None,
    with_reentry: bool = False,
    with_zone_exits: bool = False,
    with_purchase_event: bool = False,
) -> VisitSession:
    """Seed one visitor journey with configurable zone and purchase signals."""
    now = NOW()
    started = started_at or (now - timedelta(hours=1))
    visit = VisitSession(
        id=uuid.uuid4(),
        store_id=store_id,
        external_track_id=track_id or f"track-{uuid.uuid4().hex[:8]}",
        status="completed",
        started_at=started,
        ended_at=started + timedelta(minutes=55),
    )
    session.add(visit)
    await session.flush()

    zones = zone_types or ["browse", "checkout"]
    if with_reentry:
        zones = zones + ["browse"]

    track = visit.external_track_id or f"track-{visit.id.hex[:8]}"
    base_time = started + timedelta(minutes=5)
    zone_ids = {zone: f"zone-{zone}" for zone in set(zones)}
    for index, zone_type in enumerate(zones):
        entered_at = base_time + timedelta(minutes=index * 10)
        zone_id = zone_ids[zone_type]
        session.add(
            Event(
                store_id=store_id,
                tenant_id=tenant_id,
                session_id=visit.id,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": zone_type,
                    "zone_id": zone_id,
                    "zone_name": zone_type,
                    "external_track_id": track,
                    "class_label": "visitor",
                },
                correlation_id=f"enter-{index}",
                occurred_at=entered_at,
            )
        )
        if with_zone_exits:
            session.add(
                Event(
                    store_id=store_id,
                    tenant_id=tenant_id,
                    session_id=visit.id,
                    event_type="vision.zone.exited",
                    schema_version="1.0.0",
                    aggregate_type="zone",
                    aggregate_id=uuid.uuid4(),
                    payload={
                        "zone_type": zone_type,
                        "zone_id": zone_id,
                        "dwell_ms": 30_000 + index * 5_000,
                        "external_track_id": track,
                        "class_label": "visitor",
                    },
                    correlation_id=f"exit-{index}",
                    occurred_at=entered_at + timedelta(minutes=5),
                )
            )

    if with_purchase:
        session.add(
            Transaction(
                store_id=store_id,
                session_id=visit.id,
                external_ref=f"POS-{visit.id.hex[:8]}",
                amount=purchase_amount,
                occurred_at=started + timedelta(minutes=50),
            )
        )

    if with_purchase_event:
        session.add(
            Event(
                store_id=store_id,
                tenant_id=tenant_id,
                session_id=visit.id,
                event_type="analytics.purchase.completed",
                schema_version="1.0.0",
                aggregate_type="transaction",
                aggregate_id=uuid.uuid4(),
                payload={"funnel_stage": "PURCHASE", "amount": float(purchase_amount)},
                correlation_id="purchase-event",
                occurred_at=started + timedelta(minutes=50),
            )
        )

    await session.flush()
    return visit


async def seed_checkout_visits(
    session: AsyncSession,
    store_id: uuid.UUID,
    *,
    count: int,
    window_start: datetime,
    window_end: datetime,
    tenant_id: uuid.UUID = DEMO_TENANT_ID,
) -> None:
    """Seed queue/billing zone enter events spread across a time window."""
    for occurred_at in _spread_times(count, window_start, window_end):
        session.add(
            Event(
                store_id=store_id,
                tenant_id=tenant_id,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"zone_type": "checkout", "zone_name": "Checkout Queue"},
                correlation_id=f"queue-{uuid.uuid4().hex[:6]}",
                occurred_at=occurred_at,
            )
        )
    await session.flush()


async def seed_conversion_cohort(
    session: AsyncSession,
    store_id: uuid.UUID,
    *,
    entry_count: int,
    purchase_count: int,
    window_start: datetime,
    window_end: datetime,
    tenant_id: uuid.UUID = DEMO_TENANT_ID,
) -> None:
    """Seed sessions in a window with a controlled purchase ratio."""
    start_times = _spread_times(entry_count, window_start, window_end)
    for index, started_at in enumerate(start_times):
        await seed_visit_session(
            session,
            store_id,
            tenant_id=tenant_id,
            track_id=f"cohort-{window_start.timestamp()}-{index}",
            started_at=started_at,
            with_purchase=index < purchase_count,
            zone_types=["browse", "checkout"],
        )


async def seed_frame_event(
    session: AsyncSession,
    store_id: uuid.UUID,
    *,
    occurred_at: datetime,
    tenant_id: uuid.UUID = DEMO_TENANT_ID,
    frame_index: int = 1,
) -> Event:
    event = Event(
        store_id=store_id,
        tenant_id=tenant_id,
        event_type="vision.frame.processed",
        schema_version="1.0.0",
        aggregate_type="pipeline_run",
        aggregate_id=uuid.uuid4(),
        payload={"frame_index": frame_index},
        correlation_id=f"frame-{frame_index}",
        occurred_at=occurred_at,
    )
    session.add(event)
    await session.flush()
    return event


async def seed_all_stage_events(
    session: AsyncSession,
    store_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID = DEMO_TENANT_ID,
) -> VisitSession:
    """Seed every vision/analytics event type used by the analytics engines."""
    now = NOW()
    visit = await seed_visit_session(
        session,
        store_id,
        tenant_id=tenant_id,
        track_id="full-stage-track",
        started_at=now - timedelta(hours=2),
        with_purchase=True,
        with_zone_exits=True,
        with_purchase_event=True,
        zone_types=["entry", "browse", "checkout"],
    )
    await seed_frame_event(
        session,
        store_id,
        tenant_id=tenant_id,
        occurred_at=now - timedelta(minutes=5),
        frame_index=42,
    )
    return visit
