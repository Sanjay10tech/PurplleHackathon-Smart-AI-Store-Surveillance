# Re-ID evidence API and P0 solo handoff tests.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models import Event
from pipeline.tracker import GlobalIdentityRegistry


def test_p0_solo_handoff_links_entry_to_floor() -> None:
    store_id = "00000000-0000-0000-0000-000000000101"
    entry_cam = "00000000-0000-0000-0000-000000000203"
    floor_cam = "00000000-0000-0000-0000-000000000201"
    now = datetime.now(tz=UTC)

    gir = GlobalIdentityRegistry(
        store_id,
        reid_cfg={
            "enabled": True,
            "p0_solo_handoff_enabled": True,
            "cosine_threshold": 0.99,
            "match_score_threshold": 0.99,
            "handoff_seconds": {"entry_to_floor": 150},
        },
        camera_graph=[
            {"from": entry_cam, "to": floor_cam, "priority": "P0"},
        ],
        camera_roles={entry_cam: "entry", floor_cam: "floor"},
    )

    entry_id = gir.resolve(
        camera_id=entry_cam,
        local_track_id=1,
        embedding=None,
        now=now,
        role_hint="visitor",
    )
    floor_id = gir.resolve(
        camera_id=floor_cam,
        local_track_id=1,
        embedding=None,
        now=now + timedelta(seconds=30),
        role_hint="visitor",
    )
    assert entry_id == floor_id


@pytest.mark.asyncio
async def test_reid_evidence_api(client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/reid/evidence")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == str(seeded_store)
    assert "cross_camera_track_count" in body
    assert "pipeline_strategy" in body


@pytest.mark.asyncio
async def test_reid_evidence_cross_camera_detection(
    db_session_factory, seeded_store: uuid.UUID
) -> None:
    from app.repositories.event_repository import EventRepository
    from app.repositories.store_repository import StoreRepository
    from app.services.reid_evidence_service import ReIdEvidenceService

    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    track_id = f"{seeded_store}:shared-track-001"
    cam_a = "00000000-0000-0000-0000-000000000203"
    cam_b = "00000000-0000-0000-0000-000000000201"
    now = datetime.now(tz=UTC)

    async with db_session_factory() as session:
        for cam, offset in ((cam_a, 0), (cam_b, 60)):
            session.add(
                Event(
                    store_id=seeded_store,
                    tenant_id=tenant_id,
                    event_type="vision.zone.entered",
                    schema_version="1.0.0",
                    aggregate_type="zone",
                    aggregate_id=uuid.uuid4(),
                    payload={
                        "external_track_id": track_id,
                        "camera_id": cam,
                        "zone_type": "aisle",
                        "class_label": "visitor",
                    },
                    correlation_id=f"reid-{cam[-4:]}",
                    occurred_at=now + timedelta(seconds=offset),
                )
            )
        await session.commit()

    async with db_session_factory() as session:
        svc = ReIdEvidenceService(EventRepository(session), StoreRepository(session))
        evidence = await svc.get_evidence(
            seeded_store,
            from_ts=now - timedelta(hours=1),
            to_ts=now + timedelta(hours=2),
        )
        matching = [t for t in evidence.cross_camera_tracks if t.external_track_id == track_id]
        assert matching, evidence.cross_camera_tracks
        assert matching[0].camera_count >= 2
