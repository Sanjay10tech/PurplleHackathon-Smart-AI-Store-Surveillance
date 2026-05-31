"""Verify dashboard API endpoints return HTTP 200."""
from __future__ import annotations

import sys

import httpx

STORE = "00000000-0000-0000-0000-000000000101"
BASE = "http://localhost:8000"
HEADERS = {"X-API-Key": "purple-demo-key"}


def main() -> int:
    paths = [
        "/health",
        f"/api/v1/stores/{STORE}/dashboard/summary",
        f"/api/v1/stores/{STORE}/funnel",
        f"/api/v1/stores/{STORE}/funnel/journeys",
        f"/api/v1/stores/{STORE}/heatmap",
        f"/api/v1/stores/{STORE}/metrics",
        f"/api/v1/stores/{STORE}/anomalies",
    ]
    failed = False
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=30) as client:
        for path in paths:
            response = client.get(path)
            print(f"{path} -> {response.status_code}")
            if response.status_code >= 400:
                failed = True
                print(response.text[:800])

        summary = client.get(f"/api/v1/stores/{STORE}/dashboard/summary")
        if summary.status_code == 200:
            print("\nKPI sample:")
            for kpi in summary.json().get("kpis", [])[:8]:
                print(f"  {kpi['key']}: {kpi.get('formatted')}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
