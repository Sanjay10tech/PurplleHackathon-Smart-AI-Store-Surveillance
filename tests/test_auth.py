# PROMPT:
# API key authentication — protected routes, WebSocket key, and dev bypass.

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database import get_db_session
from app.main import create_app


@pytest.fixture
async def auth_app_client(db_session_factory) -> AsyncGenerator[AsyncClient, None]:
    os.environ["API_KEY"] = "test-secret-key"
    os.environ["API_KEY_REQUIRED"] = "true"
    get_settings.cache_clear()

    app = create_app()

    async def override_get_db():
        async with db_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ingest_rejects_missing_api_key(auth_app_client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await auth_app_client.post(
        "/api/v1/events/ingest",
        json={
            "event_type": "vision.frame.processed",
            "occurred_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "store_id": str(seeded_store),
            "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
            "payload": {},
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ingest_accepts_valid_api_key(auth_app_client: AsyncClient, seeded_store: uuid.UUID) -> None:
    response = await auth_app_client.post(
        "/api/v1/events/ingest",
        json={
            "event_type": "vision.frame.processed",
            "occurred_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "store_id": str(seeded_store),
            "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
            "payload": {},
        },
        headers={"X-API-Key": "test-secret-key"},
    )
    assert response.status_code == 202
