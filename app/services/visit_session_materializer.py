"""Materialize VisitSession rows from ingested CCTV vision events.

The live pipeline persists sessions when ``persist_sessions`` is enabled. Bootstrap
JSONL and first-boot ingest only write events — this service closes the gap so
funnel ENTRY, dashboard sessions, and POS linkage share the same track identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.vision.filters import is_customer_metric_event
from app.models import Event, VisitSession

ENTRY_ZONE_TYPES = frozenset({"entry_threshold", "entrance", "entry"})
STAFF_ZONE_TYPES = frozenset({"staff_only", "ignore"})
TRACK_EVENT_TYPES = (
    "vision.zone.entered",
    "vision.zone.exited",
    "vision.track.started",
    "vision.track.ended",
)


@dataclass
class TrackTimeline:
    external_track_id: str
    first_at: datetime | None = None
    last_at: datetime | None = None
    ended_at: datetime | None = None
    store_entry: bool = False
    is_staff: bool = False
    event_ids: list[UUID] = field(default_factory=list)


def _session_id_for_track(external_track_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"track:{external_track_id}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _track_from_payload(payload: dict) -> str | None:
    track_id = payload.get("external_track_id")
    return str(track_id) if track_id else None


def _merge_timeline(timeline: TrackTimeline, event: Event) -> None:
    payload = event.payload or {}
    at = _as_utc(event.occurred_at)
    timeline.event_ids.append(event.id)

    if timeline.first_at is None or at < timeline.first_at:
        timeline.first_at = at
    if timeline.last_at is None or at > timeline.last_at:
        timeline.last_at = at

    if str(payload.get("class_label", "")).lower() == "staff":
        timeline.is_staff = True

    zone_type = str(payload.get("zone_type") or "").lower()
    if zone_type in STAFF_ZONE_TYPES:
        timeline.is_staff = True

    if event.event_type == "vision.zone.entered":
        if payload.get("is_store_entry") in (True, "true", "True", "1"):
            timeline.store_entry = True
        if zone_type in ENTRY_ZONE_TYPES:
            timeline.store_entry = True
        elif is_customer_metric_event(payload):
            timeline.store_entry = True

    if event.event_type == "vision.track.ended":
        last_seen = payload.get("last_seen")
        if isinstance(last_seen, str):
            try:
                parsed = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                timeline.ended_at = _as_utc(parsed)
            except ValueError:
                timeline.ended_at = at
        else:
            timeline.ended_at = at


async def materialize_visit_sessions(
    session: AsyncSession,
    store_id: UUID,
) -> dict[str, int]:
    """Create customer VisitSession rows from vision events (idempotent)."""
    event_rows = await session.execute(
        select(Event)
        .where(
            Event.store_id == store_id,
            Event.event_type.in_(TRACK_EVENT_TYPES),
        )
        .order_by(Event.occurred_at.asc())
    )
    events = list(event_rows.scalars())

    existing_rows = await session.execute(
        select(VisitSession).where(VisitSession.store_id == store_id)
    )
    existing_by_track = {
        row.external_track_id: row
        for row in existing_rows.scalars()
        if row.external_track_id
    }

    timelines: dict[str, TrackTimeline] = {}
    for event in events:
        track_id = _track_from_payload(event.payload or {})
        if not track_id:
            continue
        timeline = timelines.setdefault(track_id, TrackTimeline(external_track_id=track_id))
        _merge_timeline(timeline, event)

    created = 0
    backfilled = 0
    skipped_staff = 0

    for track_id, timeline in timelines.items():
        if timeline.is_staff or timeline.first_at is None:
            skipped_staff += int(timeline.is_staff)
            continue
        if track_id in existing_by_track:
            visit = existing_by_track[track_id]
        else:
            visit = VisitSession(
                id=_session_id_for_track(track_id),
                store_id=store_id,
                external_track_id=track_id,
                status="completed" if timeline.ended_at else "active",
                started_at=timeline.first_at,
                ended_at=timeline.ended_at or timeline.last_at,
                metadata_={
                    "store_entry": timeline.store_entry,
                    "materialized_from": "vision_events",
                },
            )
            session.add(visit)
            existing_by_track[track_id] = visit
            created += 1

        for event in events:
            if event.id not in timeline.event_ids:
                continue
            if event.session_id is None:
                event.session_id = visit.id
                backfilled += 1

    return {
        "tracks_seen": len(timelines),
        "sessions_created": created,
        "events_backfilled": backfilled,
        "staff_tracks_skipped": skipped_staff,
    }
