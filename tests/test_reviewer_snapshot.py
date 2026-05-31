"""Tests for public reviewer snapshot endpoint."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.config import get_settings


@pytest.mark.asyncio
async def test_reviewer_snapshot_public(
    client: AsyncClient, seeded_store: uuid.UUID
) -> None:
    response = await client.get("/reviewer")
    assert response.status_code == 200
    body = response.json()
    assert body["demo_store_id"] == "00000000-0000-0000-0000-000000000101"
    assert body["checks_total"] == 8
    assert len(body["checks"]) == 8
    assert "endpoints" in body
    assert body["dashboard_url"] == "/dashboard/"
    assert body["api_guide_url"] == "/reviewer/api"
    assert body["reviewer_mode"] is True
    assert body["api_key_hint"] == "purple-demo-key"


@pytest.mark.asyncio
async def test_reviewer_api_guide(client: AsyncClient) -> None:
    response = await client.get("/reviewer/api")
    assert response.status_code == 200
    body = response.json()
    assert body["reviewer_mode"] is True
    assert body["api_key"] == "purple-demo-key"
    assert body["demo_store_id"] == "00000000-0000-0000-0000-000000000101"
    assert body["auth_header"] == "X-API-Key"
    assert len(body["routes"]) >= 10
    funnel = next(r for r in body["routes"] if r["name"] == "Funnel")
    assert "purple-demo-key" in funnel["curl"]
    assert "00000000-0000-0000-0000-000000000101" in funnel["path"]


@pytest.mark.asyncio
async def test_reviewer_mode_accepts_demo_key(
    client: AsyncClient, seeded_store: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("REVIEWER_MODE", "true")
    monkeypatch.setenv("API_KEY", "production-secret")
    monkeypatch.setenv("API_KEY_REQUIRED", "true")
    get_settings.cache_clear()

    bad = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    assert bad.status_code == 401

    ok = await client.get(
        f"/api/v1/stores/{seeded_store}/funnel",
        headers={"X-API-Key": "purple-demo-key"},
    )
    assert ok.status_code == 200
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health_includes_reviewer_block(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "reviewer" in body
    assert body["reviewer"]["demo_store_id"] == "00000000-0000-0000-0000-000000000101"
    assert "endpoints" in body["reviewer"]
