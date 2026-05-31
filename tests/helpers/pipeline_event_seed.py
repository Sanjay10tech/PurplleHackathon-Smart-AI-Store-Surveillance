"""Realistic retail test data shaped like pipeline/emit.py output."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, StoreMetric, Transaction, VisitSession
from pipeline.emit import EventBuilder
from pipeline.tracker import FramePipelineResult, TrackState, ZoneTransition
from tests.helpers.constants import DEMO_TENANT_ID
from tests.helpers.seed import seed_frame_event

CAM_ENTRY = "00000000-0000-0000-0000-000000000203"
CAM_BILLING = "00000000-0000-0000-0000-000000000205"
ZONE_ENTRY = "zone-cam3-entry-threshold"
ZONE_BROWSE = "zone-cam1-browse-left"
ZONE_QUEUE = "zone-cam5-queue"


@dataclass(frozen=True)
class RetailDayExpectations:
    unique_visitors: int
    purchase_count: int
    conversion_rate: float
    billing_queue_visits: int
    queue_spike_ratio_min: float
    staff_events_ingested: int


def _builder(store_id: uuid.UUID, tenant_id: uuid.UUID, correlation_id: str) -> EventBuilder:
    return EventBuilder(
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        schema_version="1.0.0",
        pipeline_run_id=uuid.uuid4(),
        correlation_id=correlation_id,
    )


def build_visitor_journey_events(
    *,
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    external_track_id: str,
    started_at: datetime,
    with_purchase: bool = False,
    with_reentry: bool = False,
    correlation_id: str = "retail-day",
) -> list[dict]:
    """Build ingest-ready events mirroring pipeline emit payloads."""
    builder = _builder(store_id, tenant_id, correlation_id)
    track = TrackState(
        local_track_id=1,
        global_id=external_track_id,
        camera_id=CAM_ENTRY,
        bbox_xywh=(0.42, 0.35, 0.08, 0.22),
        confidence=0.91,
        foot_point=(0.46, 0.57),
        session_id=session_id,
        class_label="visitor",
    )

    events: list[dict] = []
    t = started_at

    entry = builder.zone_event(
        track,
        ZoneTransition(
            event_type="vision.zone.entered",
            zone_id=ZONE_ENTRY,
            zone_name="entry_threshold",
            zone_type="entry_threshold",
            direction="in",
        ),
        occurred_at=t,
    )
    if entry:
        events.append(entry)

    browse = builder.zone_event(
        track,
        ZoneTransition(
            event_type="vision.zone.entered",
            zone_id=ZONE_BROWSE,
            zone_name="browse_skincare_wall",
            zone_type="browse",
        ),
        occurred_at=t + timedelta(minutes=8),
    )
    if browse:
        events.append(browse)

    if with_reentry:
        reentry = builder.zone_event(
            track,
            ZoneTransition(
                event_type="vision.zone.entered",
                zone_id=ZONE_BROWSE,
                zone_name="browse_skincare_wall",
                zone_type="browse",
                is_reentry=True,
            ),
            occurred_at=t + timedelta(minutes=18),
        )
        if reentry:
            events.append(reentry)

    queue = builder.zone_event(
        track,
        ZoneTransition(
            event_type="vision.zone.entered",
            zone_id=ZONE_QUEUE,
            zone_name="billing_queue",
            zone_type="billing_queue",
        ),
        occurred_at=t + timedelta(minutes=25),
    )
    if queue:
        events.append(queue)

    frame = builder.frame_processed(
        FramePipelineResult(
            camera_id=CAM_ENTRY,
            frame_index=100,
            frame_timestamp=t + timedelta(minutes=1),
            tracks=[track],
            zone_transitions=[],
            ended_tracks=[],
        ),
        processing_ms=38,
    )
    events.append(frame)

    if with_purchase:
        events.append(
            {
                "event_type": "analytics.purchase.completed",
                "schema_version": "1.0.0",
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "occurred_at": (t + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
                "correlation_id": correlation_id,
                "idempotency_key": f"purchase-{session_id}",
                "aggregate": {"type": "transaction", "id": str(uuid.uuid4())},
                "payload": {
                    "store_id": str(store_id),
                    "session_id": str(session_id),
                    "funnel_stage": "PURCHASE",
                    "amount": 24.99,
                },
            }
        )

    return events


def build_staff_zone_event(
    *,
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    occurred_at: datetime,
    correlation_id: str = "staff-event",
) -> dict:
    builder = _builder(store_id, tenant_id, correlation_id)
    track = TrackState(
        local_track_id=99,
        global_id=f"{store_id}:staff-1",
        camera_id=CAM_BILLING,
        bbox_xywh=(0.35, 0.32, 0.08, 0.22),
        confidence=0.88,
        foot_point=(0.39, 0.54),
        session_id=uuid.uuid4(),
        class_label="staff",
        is_staff=True,
    )
    event = builder.zone_event(
        track,
        ZoneTransition(
            event_type="vision.zone.entered",
            zone_id="zone-cam5-staff",
            zone_name="checkout_staff",
            zone_type="staff_only",
        ),
        occurred_at=occurred_at,
    )
    assert event is not None
    return event


async def _persist_event_dicts(
    session: AsyncSession,
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    event_dicts: list[dict],
) -> int:
    count = 0
    for raw in event_dicts:
        payload = dict(raw["payload"])
        session_id_raw = payload.get("session_id")
        session.add(
            Event(
                id=uuid.UUID(raw["event_id"]) if raw.get("event_id") else uuid.uuid4(),
                store_id=store_id,
                tenant_id=tenant_id,
                session_id=uuid.UUID(str(session_id_raw)) if session_id_raw else None,
                event_type=raw["event_type"],
                schema_version=raw.get("schema_version", "1.0.0"),
                aggregate_type=raw["aggregate"]["type"],
                aggregate_id=uuid.UUID(str(raw["aggregate"]["id"])),
                payload=payload,
                correlation_id=raw.get("correlation_id"),
                idempotency_key=raw.get("idempotency_key"),
                occurred_at=datetime.fromisoformat(raw["occurred_at"].replace("Z", "+00:00")),
            )
        )
        count += 1
    return count


async def seed_pipeline_retail_day(
    session: AsyncSession,
    store_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID = DEMO_TENANT_ID,
    anchor: datetime | None = None,
) -> RetailDayExpectations:
    """
    Seed a realistic retail day using pipeline-shaped events.

    - 10 visitors, 3 purchases (30% conversion)
    - 1 visitor with browse re-entry
    - Queue spike in current window vs baseline
    - Staff zone event (excluded from customer metrics)
    - Hourly footfall metric bucket
    """
    now = anchor or datetime.now(tz=UTC)
    period_end = now
    period_start = now - timedelta(hours=24)
    baseline_end = period_start
    baseline_start = baseline_end - timedelta(hours=24)

    purchase_count = 0
    billing_queue_visits = 0

    for index in range(10):
        started_at = period_end - timedelta(hours=10 - index, minutes=index * 3)
        visit = VisitSession(
            id=uuid.uuid4(),
            store_id=store_id,
            external_track_id=f"{store_id}:visitor-{index}",
            status="completed",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=45),
        )
        session.add(visit)
        await session.flush()

        with_purchase = index < 3
        if with_purchase:
            purchase_count += 1
            session.add(
                Transaction(
                    store_id=store_id,
                    session_id=visit.id,
                    external_ref=f"POS-{index:04d}",
                    amount=Decimal("24.99"),
                    occurred_at=started_at + timedelta(minutes=30),
                )
            )

        journey = build_visitor_journey_events(
            store_id=store_id,
            tenant_id=tenant_id,
            session_id=visit.id,
            external_track_id=visit.external_track_id or f"visitor-{index}",
            started_at=started_at,
            with_purchase=with_purchase,
            with_reentry=index == 0,
            correlation_id=f"visitor-{index}",
        )
        billing_queue_visits += 1
        await _persist_event_dicts(session, store_id, tenant_id, journey)

    # Baseline queue traffic (low) — zone_type key matches anomaly queue_zone_keys
    for i in range(8):
        session.add(
            Event(
                store_id=store_id,
                tenant_id=tenant_id,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "billing_queue",
                    "zone_name": "billing_queue",
                    "class_label": "visitor",
                },
                correlation_id=f"baseline-queue-{i}",
                occurred_at=baseline_start + timedelta(hours=4 + i),
            )
        )

    # Current window queue spike
    for i in range(28):
        session.add(
            Event(
                store_id=store_id,
                tenant_id=tenant_id,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "zone_type": "billing_queue",
                    "zone_name": "billing_queue",
                    "class_label": "visitor",
                },
                correlation_id=f"spike-queue-{i}",
                occurred_at=period_end - timedelta(hours=2, minutes=i * 5),
            )
        )
    billing_queue_visits += 28

    staff_event = build_staff_zone_event(
        store_id=store_id,
        tenant_id=tenant_id,
        occurred_at=period_end - timedelta(hours=1),
    )
    await _persist_event_dicts(session, store_id, tenant_id, [staff_event])

    await seed_frame_event(
        session,
        store_id,
        tenant_id=tenant_id,
        occurred_at=period_end - timedelta(minutes=2),
        frame_index=999,
    )

    bucket = (now - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    session.add(
        StoreMetric(
            store_id=store_id,
            metric_name="footfall.count",
            bucket_start=bucket,
            bucket_end=bucket + timedelta(hours=1),
            granularity="hour",
            dimensions={},
            value=10.0,
            sample_count=10,
        )
    )

    await session.flush()
    return RetailDayExpectations(
        unique_visitors=10,
        purchase_count=purchase_count,
        conversion_rate=0.3,
        billing_queue_visits=billing_queue_visits,
        queue_spike_ratio_min=1.5,
        staff_events_ingested=1,
    )
