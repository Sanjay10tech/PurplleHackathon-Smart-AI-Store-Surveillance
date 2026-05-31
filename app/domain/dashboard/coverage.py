"""Event coverage metadata — cameras, videos, frames visible in dashboard."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event

CAMERA_VIDEO_LABELS: dict[str, str] = {
    "00000000-0000-0000-0000-000000000201": "CAM 1.mp4",
    "00000000-0000-0000-0000-000000000202": "CAM 2.mp4",
    "00000000-0000-0000-0000-000000000203": "CAM 3.mp4",
    "00000000-0000-0000-0000-000000000204": "CAM 4.mp4",
    "00000000-0000-0000-0000-000000000205": "CAM 5.mp4",
}

EXPECTED_SOURCE_VIDEOS: list[str] = list(CAMERA_VIDEO_LABELS.values())


def _video_basename(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _strip_json_string(value) or value
    # Normalize Windows/Unix paths and duplicates like C:\...\CAM 1.mp4 → CAM 1.mp4
    name = cleaned.replace("\\", "/").split("/")[-1].strip()
    return name or None


def _normalize_source_videos(values: list[str]) -> list[str]:
    basenames = {_video_basename(v) for v in values if v}
    return sorted(b for b in basenames if b)


def _strip_json_string(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


async def _coverage_postgres(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> dict[str, object]:
    params = {"store_id": store_id, "from_ts": from_ts, "to_ts": to_ts}

    total_in_period = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM events
                WHERE store_id = :store_id
                  AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                """
            ),
            params,
        )
    ).scalar_one()

    total_all_time = (
        await session.execute(
            text("SELECT COUNT(*) FROM events WHERE store_id = :store_id"),
            {"store_id": store_id},
        )
    ).scalar_one()

    camera_rows = (
        await session.execute(
            text(
                """
                SELECT payload->>'camera_id' AS camera_id, COUNT(*) AS event_count
                FROM events
                WHERE store_id = :store_id
                  AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                  AND payload->>'camera_id' IS NOT NULL
                GROUP BY 1
                ORDER BY 2 DESC
                """
            ),
            params,
        )
    ).all()

    video_rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT payload->>'source_video' AS source_video
                FROM events
                WHERE store_id = :store_id
                  AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                  AND payload->>'source_video' IS NOT NULL
                  AND payload->>'source_video' != ''
                """
            ),
            params,
        )
    ).all()

    frame_rows = (
        await session.execute(
            text(
                """
                SELECT payload->>'camera_id' AS camera_id,
                       MAX((payload->>'frame_index')::int) AS max_frame_index,
                       COUNT(*) AS frame_events
                FROM events
                WHERE store_id = :store_id
                  AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                  AND event_type = 'vision.frame.processed'
                GROUP BY 1
                """
            ),
            params,
        )
    ).all()

    detector_rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT payload->>'detector_mode' AS mode
                FROM events
                WHERE store_id = :store_id
                  AND occurred_at >= :from_ts AND occurred_at <= :to_ts
                  AND payload->>'detector_mode' IS NOT NULL
                """
            ),
            params,
        )
    ).all()

    return _build_coverage_result(
        int(total_in_period),
        int(total_all_time),
        camera_rows,
        video_rows,
        frame_rows,
        detector_rows,
    )


async def _coverage_portable(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> dict[str, object]:
    total_all_time = (
        await session.execute(
            select(func.count()).select_from(Event).where(Event.store_id == store_id)
        )
    ).scalar_one()

    period_stmt = select(Event).where(
        Event.store_id == store_id,
        Event.occurred_at >= from_ts,
        Event.occurred_at <= to_ts,
    )
    events = (await session.execute(period_stmt)).scalars().all()

    camera_counts: dict[str, int] = {}
    videos: set[str] = set()
    modes: set[str] = set()
    frame_by_camera: dict[str, dict[str, int]] = {}

    for event in events:
        payload = event.payload or {}
        cam = payload.get("camera_id")
        if cam:
            camera_counts[str(cam)] = camera_counts.get(str(cam), 0) + 1
        video = payload.get("source_video")
        if video:
            videos.add(str(video))
        mode = payload.get("detector_mode")
        if mode:
            modes.add(str(mode))
        if event.event_type == "vision.frame.processed" and cam:
            bucket = frame_by_camera.setdefault(
                str(cam), {"frame_events": 0, "max_frame_index": -1}
            )
            bucket["frame_events"] += 1
            idx = payload.get("frame_index")
            if isinstance(idx, int):
                bucket["max_frame_index"] = max(bucket["max_frame_index"], idx)

    camera_rows = [(cam, count) for cam, count in sorted(camera_counts.items())]
    video_rows = [(v,) for v in videos]
    frame_rows = [
        (cam, data["max_frame_index"], data["frame_events"])
        for cam, data in frame_by_camera.items()
    ]
    detector_rows = [(m,) for m in modes]

    return _build_coverage_result(
        len(events),
        int(total_all_time),
        camera_rows,
        video_rows,
        frame_rows,
        detector_rows,
    )


def _build_coverage_result(
    total_in_period: int,
    total_all_time: int,
    camera_rows,
    video_rows,
    frame_rows,
    detector_rows,
) -> dict[str, object]:
    videos_from_payload = [_video_basename(row[0]) for row in video_rows if row[0]]
    videos_from_cameras = [
        _video_basename(CAMERA_VIDEO_LABELS.get(row[0], row[0])) for row in camera_rows if row[0]
    ]
    source_videos = _normalize_source_videos(
        [v for v in videos_from_payload + videos_from_cameras if v]
    )

    modes = sorted(m for m in (_strip_json_string(row[0]) for row in detector_rows) if m)
    if len(modes) == 1:
        detector_mode = modes[0]
    elif modes:
        detector_mode = "mixed"
    else:
        detector_mode = None

    frames_logged = sum(int(row[2] or 0) for row in frame_rows)
    max_frame_index_sum = sum(int(row[1] or 0) + 1 for row in frame_rows if row[1] is not None)

    return {
        "total_events_in_period": total_in_period,
        "total_events_all_time": total_all_time,
        "events_outside_period": total_all_time - total_in_period,
        "cameras_active": len(camera_rows),
        "camera_breakdown": [
            {
                "camera_id": row[0],
                "events": int(row[1]),
                "video": CAMERA_VIDEO_LABELS.get(row[0], row[0]),
            }
            for row in camera_rows
        ],
        "source_videos": source_videos,
        "frames_logged": frames_logged,
        "frames_index_ceiling": max_frame_index_sum,
        "detector_mode": detector_mode,
        "processing_lineage": (
            "mock_trajectory_pipeline"
            if detector_mode == "mock"
            else "yolo_cctv_pipeline"
            if detector_mode == "yolo"
            else "ingested_events_missing_detector_mode"
            if total_in_period
            else None
        ),
    }


async def get_event_coverage(
    session: AsyncSession,
    store_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> dict[str, object]:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return await _coverage_postgres(session, store_id, from_ts, to_ts)
    return await _coverage_portable(session, store_id, from_ts, to_ts)
