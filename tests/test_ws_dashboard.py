# PROMPT:
# WebSocket live feed smoke test for dashboard bonus coverage.

from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.config import get_settings
from app.database import get_db_session
from app.main import create_app


@pytest.mark.asyncio
async def test_dashboard_static_served(client: AsyncClient) -> None:
    response = await client.get("/dashboard/")
    assert response.status_code == 200
    assert "Store Intelligence" in response.text


def test_websocket_live_feed(db_session_factory, seeded_store: uuid.UUID) -> None:
    os.environ["API_KEY_REQUIRED"] = "false"
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
    client = TestClient(app)
    with client.websocket_connect(f"/ws/stores/{seeded_store}/live") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "funnel" in msg
        assert "heatmap" in msg
        assert "metrics" in msg
    app.dependency_overrides.clear()
    get_settings.cache_clear()
