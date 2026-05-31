# PROMPT:
# Generate complete pytest suite scenario: empty store with no vision events or sessions.
# Assert all analytics endpoints return stable empty-state metadata and zero counts.
#
# CHANGES MADE:
# - End-to-end API tests for metrics, funnel, heatmap, and anomalies on a seeded store
#   with no ingested events or sessions.
# - Validates meta.source empty-engine variants and zeroed funnel stage counts.

from uuid import UUID

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_funnel_empty_store_api(client: AsyncClient, seeded_store: UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/funnel")
    assert response.status_code == 200
    body = response.json()
    assert body["unique_visitors"] == 0
    assert body["meta"]["source"] == "funnel_engine_empty"
    assert all(stage["count"] == 0 for stage in body["stages"])


@pytest.mark.asyncio
async def test_heatmap_empty_store_api(client: AsyncClient, seeded_store: UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/heatmap")
    assert response.status_code == 200
    body = response.json()
    assert body["zones"] == []
    assert body["meta"]["source"] == "heatmap_engine_empty"
    assert body["meta"]["data_confidence"] == "LOW"
    assert body["meta"]["total_visits"] == 0


@pytest.mark.asyncio
async def test_anomalies_empty_store_api(client: AsyncClient, seeded_store: UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/anomalies")
    assert response.status_code == 200
    body = response.json()
    types = {item["anomaly_type"] for item in body["items"]}
    assert "STALE_FEED" in types
    assert body["meta"]["source"] in {"anomaly_engine", "anomaly_engine_empty"}


@pytest.mark.asyncio
async def test_metrics_empty_store_placeholder(client: AsyncClient, seeded_store: UUID) -> None:
    response = await client.get(f"/api/v1/stores/{seeded_store}/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["series"] == []
    assert body["meta"]["source"] == "placeholder"


@pytest.mark.asyncio
async def test_funnel_service_empty_store(funnel_service, seeded_store: UUID) -> None:
    service, _session = funnel_service
    result = await service.get_funnel(seeded_store)
    assert result.unique_visitors == 0
    assert result.meta["partial"] is True


@pytest.mark.asyncio
async def test_heatmap_service_empty_store(heatmap_service, seeded_store: UUID) -> None:
    service, _session = heatmap_service
    result = await service.get_heatmap(seeded_store)
    assert result.meta["total_visits"] == 0
    assert result.meta["partial"] is True
