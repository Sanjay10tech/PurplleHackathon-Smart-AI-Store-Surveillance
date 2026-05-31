"""Reviewer API catalog — demo store URLs and curl examples."""

from __future__ import annotations

from app.config import Settings

DEMO_API_KEY = "purple-demo-key"
DEMO_STORE_ID = "00000000-0000-0000-0000-000000000101"


def build_reviewer_api_guide(settings: Settings, *, api_base_url: str | None = None) -> dict[str, object]:
    """Structured API guide for Purple Tech evaluators."""
    store_id = settings.pos_store_id or DEMO_STORE_ID
    api_key = settings.effective_api_key
    base = (api_base_url or settings.reviewer_api_base_url).rstrip("/")
    store_base = f"{base}/api/v1/stores/{store_id}"

    def _curl(method: str, path: str, *, auth: bool = False) -> str:
        url = f"{base}{path}" if path.startswith("/") else path
        if method == "GET" and not auth:
            return f'curl "{url}"'
        if method == "GET" and auth:
            return f'curl -H "X-API-Key: {api_key}" "{url}"'
        return f'curl -X {method} -H "X-API-Key: {api_key}" -H "Content-Type: application/json" "{url}"'

    routes: list[dict[str, object]] = [
        {
            "name": "Health",
            "method": "GET",
            "path": "/health",
            "auth_required": False,
            "description": "Liveness, database status, feed freshness, reviewer summary",
            "curl": _curl("GET", "/health"),
        },
        {
            "name": "Reviewer proof",
            "method": "GET",
            "path": "/reviewer",
            "auth_required": False,
            "description": "8-check proof checklist from live PostgreSQL data",
            "curl": _curl("GET", "/reviewer"),
        },
        {
            "name": "Reviewer API guide",
            "method": "GET",
            "path": "/reviewer/api",
            "auth_required": False,
            "description": "This document — all demo endpoints with curl examples",
            "curl": _curl("GET", "/reviewer/api"),
        },
        {
            "name": "Readiness",
            "method": "GET",
            "path": "/health/ready",
            "auth_required": False,
            "description": "Kubernetes/Docker readiness (PostgreSQL up)",
            "curl": _curl("GET", "/health/ready"),
        },
        {
            "name": "Metrics",
            "method": "GET",
            "path": f"/api/v1/stores/{store_id}/metrics?metric=visitor.count",
            "auth_required": True,
            "description": "Footfall / visitor time series",
            "curl": _curl("GET", f"{store_base}/metrics?metric=visitor.count", auth=True),
        },
        {
            "name": "Funnel",
            "method": "GET",
            "path": f"/api/v1/stores/{store_id}/funnel",
            "auth_required": True,
            "description": "ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE",
            "curl": _curl("GET", f"{store_base}/funnel", auth=True),
        },
        {
            "name": "Heatmap",
            "method": "GET",
            "path": f"/api/v1/stores/{store_id}/heatmap",
            "auth_required": True,
            "description": "Zone visit density and dwell",
            "curl": _curl("GET", f"{store_base}/heatmap", auth=True),
        },
        {
            "name": "Anomalies",
            "method": "GET",
            "path": f"/api/v1/stores/{store_id}/anomalies",
            "auth_required": True,
            "description": "Rule-detected operational alerts",
            "curl": _curl("GET", f"{store_base}/anomalies", auth=True),
        },
        {
            "name": "Dashboard summary",
            "method": "GET",
            "path": f"/api/v1/stores/{store_id}/dashboard/summary",
            "auth_required": True,
            "description": "KPIs, POS linkage, reviewer evidence",
            "curl": _curl("GET", f"{store_base}/dashboard/summary", auth=True),
        },
        {
            "name": "Retail journeys",
            "method": "GET",
            "path": f"/api/v1/stores/{store_id}/funnel/journeys",
            "auth_required": True,
            "description": "Per-visitor journey paths",
            "curl": _curl("GET", f"{store_base}/funnel/journeys", auth=True),
        },
        {
            "name": "Re-ID evidence",
            "method": "GET",
            "path": f"/api/v1/stores/{store_id}/reid/evidence",
            "auth_required": True,
            "description": "Cross-camera track linkage proof",
            "curl": _curl("GET", f"{store_base}/reid/evidence", auth=True),
        },
        {
            "name": "OpenAPI",
            "method": "GET",
            "path": "/docs",
            "auth_required": False,
            "description": "Interactive Swagger UI — click Authorize, enter demo API key",
            "curl": f"open {base}/docs",
        },
    ]

    return {
        "reviewer_mode": settings.reviewer_mode,
        "api_base_url": base,
        "demo_store_id": store_id,
        "api_key": api_key,
        "auth_header": "X-API-Key",
        "auth_example": {"X-API-Key": api_key},
        "quick_start": [
            "docker compose up --build",
            f'curl "{base}/health"',
            f'curl "{base}/reviewer"',
            f'curl -H "X-API-Key: {api_key}" "{store_base}/funnel"',
            f"open {base}/dashboard/",
        ],
        "routes": routes,
        "notes": [
            f"Do not use {{id}} placeholders — always use store UUID `{store_id}`.",
            "Protected routes return HTTP 401 without header X-API-Key.",
            "In reviewer mode, only the demo key above is accepted on protected routes.",
            "Public routes: /health, /reviewer, /reviewer/api, /health/ready, /dashboard/, /docs.",
        ],
    }
