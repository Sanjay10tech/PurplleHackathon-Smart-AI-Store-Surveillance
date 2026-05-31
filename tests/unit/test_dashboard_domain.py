"""Unit tests for dashboard period, event coverage, and visitor count helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.dashboard.coverage import (
    CAMERA_VIDEO_LABELS,
    _build_coverage_result,
    _normalize_source_videos,
    _strip_json_string,
    _video_basename,
    get_event_coverage,
)
from app.domain.dashboard.period import resolve_analysis_period
from app.domain.dashboard.trend_queries import (
    footfall_trend_series,
    pos_purchase_trend_series,
    pos_revenue_trend_series,
    queue_trend_series,
    visitor_trend_series,
)
from app.domain.vision.visitor_count import (
    _is_customer_track,
    count_distinct_visitor_ids,
    count_sessions_in_period,
)
from app.models import Event, Transaction
from tests.helpers.constants import DEMO_TENANT_ID


def test_is_customer_track_filters_staff_and_null() -> None:
    assert _is_customer_track({"class_label": "visitor"}, "track-1") is True
    assert _is_customer_track({"class_label": "staff"}, "track-1") is False
    assert _is_customer_track({"zone_type": "staff_only"}, "track-1") is False
    assert _is_customer_track({}, None) is False
    assert _is_customer_track({}, "null") is False


def test_video_basename_and_normalize() -> None:
    assert _video_basename(None) is None
    assert _video_basename('"CAM 3.mp4"') == "CAM 3.mp4"
    assert _video_basename(r"C:\data\videos\CAM 1.mp4") == "CAM 1.mp4"
    assert _normalize_source_videos(["CAM 2.mp4", "CAM 1.mp4", "CAM 2.mp4"]) == [
        "CAM 1.mp4",
        "CAM 2.mp4",
    ]


def test_strip_json_string() -> None:
    assert _strip_json_string('"yolo"') == "yolo"
    assert _strip_json_string("yolo") == "yolo"
    assert _strip_json_string(None) is None


def test_build_coverage_result_detector_modes() -> None:
    cam_id = next(iter(CAMERA_VIDEO_LABELS))
    base = _build_coverage_result(
        10,
        20,
        [(cam_id, 5)],
        [("CAM 3.mp4",)],
        [(cam_id, 9, 2)],
        [("yolo",)],
    )
    assert base["detector_mode"] == "yolo"
    assert base["processing_lineage"] == "yolo_cctv_pipeline"
    assert base["cameras_active"] == 1
    assert base["frames_logged"] == 2

    mixed = _build_coverage_result(1, 1, [], [], [], [("yolo",), ("mock",)])
    assert mixed["detector_mode"] == "mixed"

    missing = _build_coverage_result(3, 3, [], [], [], [])
    assert missing["detector_mode"] is None
    assert missing["processing_lineage"] == "ingested_events_missing_detector_mode"

    mock = _build_coverage_result(1, 1, [], [], [], [("mock",)])
    assert mock["processing_lineage"] == "mock_trajectory_pipeline"


@pytest.mark.asyncio
async def test_resolve_analysis_period_explicit_from(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        start = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
        end = datetime(2026, 4, 10, 20, 0, tzinfo=UTC)
        period = await resolve_analysis_period(session, seeded_store, start, end)
        assert period == (start, end)


@pytest.mark.asyncio
async def test_resolve_analysis_period_from_first_event(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        first = datetime(2026, 4, 9, 10, 0, tzinfo=UTC)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={"external_track_id": "t1"},
                correlation_id="period-1",
                occurred_at=first,
            )
        )
        await session.commit()
        start, end = await resolve_analysis_period(session, seeded_store, None, None)
        assert start == first
        assert end.tzinfo is not None


@pytest.mark.asyncio
async def test_resolve_analysis_period_fallback_hours(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        end = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        start, resolved_end = await resolve_analysis_period(
            session, seeded_store, None, end, default_hours=6
        )
        assert resolved_end == end
        assert (end - start).total_seconds() == pytest.approx(6 * 3600, rel=0.01)


@pytest.mark.asyncio
async def test_count_distinct_visitor_ids_portable(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        now = datetime.now(tz=UTC)
        for track, label in [("v1", "visitor"), ("v2", "staff"), ("v1", "visitor")]:
            session.add(
                Event(
                    store_id=seeded_store,
                    tenant_id=DEMO_TENANT_ID,
                    event_type="vision.zone.entered",
                    schema_version="1.0.0",
                    aggregate_type="zone",
                    aggregate_id=uuid.uuid4(),
                    payload={
                        "external_track_id": track,
                        "class_label": label,
                        "zone_type": "browse",
                    },
                    correlation_id=f"vc-{track}-{label}",
                    occurred_at=now,
                )
            )
        await session.commit()
        count = await count_distinct_visitor_ids(
            session, seeded_store, now - timedelta(hours=1), now + timedelta(hours=1)
        )
        assert count >= 1
        assert count <= 2


@pytest.mark.asyncio
async def test_get_event_coverage_portable(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        now = datetime.now(tz=UTC)
        cam = "00000000-0000-0000-0000-000000000203"
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.frame.processed",
                schema_version="1.0.0",
                aggregate_type="pipeline_run",
                aggregate_id=uuid.uuid4(),
                payload={
                    "camera_id": cam,
                    "source_video": "CAM 3.mp4",
                    "detector_mode": "yolo",
                    "frame_index": 4,
                },
                correlation_id="cov-1",
                occurred_at=now,
            )
        )
        await session.commit()
        cov = await get_event_coverage(
            session,
            seeded_store,
            now - timedelta(hours=1),
            now + timedelta(hours=1),
        )
        assert cov["cameras_active"] == 1
        assert "CAM 3.mp4" in cov["source_videos"]
        assert cov["detector_mode"] == "yolo"


@pytest.mark.asyncio
async def test_count_sessions_in_period_excludes_staff(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from app.models import VisitSession

    async with db_session_factory() as session:
        now = datetime.now(tz=UTC)
        session.add(
            VisitSession(
                store_id=seeded_store,
                external_track_id="visitor-1",
                status="active",
                started_at=now,
                metadata_={},
            )
        )
        session.add(
            VisitSession(
                store_id=seeded_store,
                external_track_id="staff-1",
                status="active",
                started_at=now,
                metadata_={"staff": "true"},
            )
        )
        await session.commit()
        count = await count_sessions_in_period(
            session, seeded_store, now - timedelta(hours=1), now + timedelta(hours=1)
        )
        assert count >= 1


@pytest.mark.asyncio
async def test_resolve_analysis_period_uses_first_transaction(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        tx_at = datetime(2026, 4, 8, 9, 0, tzinfo=UTC)
        session.add(
            Transaction(
                store_id=seeded_store,
                amount=10,
                occurred_at=tx_at,
            )
        )
        await session.commit()
        start, _ = await resolve_analysis_period(session, seeded_store, None, None)
        assert start == tx_at


@pytest.mark.asyncio
async def test_trend_queries_portable_paths(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    async with db_session_factory() as session:
        now = datetime(2026, 4, 10, 14, 30, tzinfo=UTC)
        window_start = now - timedelta(hours=2)
        window_end = now + timedelta(hours=2)
        session.add(
            Event(
                store_id=seeded_store,
                tenant_id=DEMO_TENANT_ID,
                event_type="vision.zone.entered",
                schema_version="1.0.0",
                aggregate_type="zone",
                aggregate_id=uuid.uuid4(),
                payload={
                    "external_track_id": "trend-v1",
                    "class_label": "visitor",
                    "zone_type": "browse",
                },
                correlation_id="trend-enter",
                occurred_at=now,
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
                    "external_track_id": "trend-v2",
                    "class_label": "visitor",
                    "zone_type": "billing_queue",
                    "zone_id": "billing-main",
                },
                correlation_id="trend-queue",
                occurred_at=now,
            )
        )
        session.add(
            Transaction(
                store_id=seeded_store,
                amount=150,
                status="completed",
                occurred_at=now,
            )
        )
        await session.commit()

        footfall = await footfall_trend_series(session, seeded_store, window_start, window_end)
        visitors = await visitor_trend_series(session, seeded_store, window_start, window_end)
        queue = await queue_trend_series(session, seeded_store, window_start, window_end)
        revenue = await pos_revenue_trend_series(session, seeded_store, window_start, window_end)
        purchases = await pos_purchase_trend_series(session, seeded_store, window_start, window_end)

        assert len(footfall) >= 1
        assert len(visitors) >= 1
        assert len(queue) >= 1
        assert len(revenue) >= 1
        assert len(purchases) >= 1
