# Dashboard Debug Report

**Generated:** 2026-05-30T19:16:58.954962+00:00
**Store ID:** `00000000-0000-0000-0000-000000000101`
**API key tested:** `purple-demo-key`

## API request matrix

| Host | Path | Status | Result | Hint |
|------|------|-------:|--------|------|
| localhost | `/health` | 200 | PASS | status=degraded db=up |
| localhost | `/dashboard/` | 200 | PASS | non-JSON |
| localhost | `/api/v1/stores/00000000-0000-0000-0000-000000000101/dashboard/summary` | 200 | PASS | non-JSON |
| localhost | `/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics` | 200 | PASS | series=0 |
| localhost | `/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel` | 200 | PASS | stages=4 visitors=0 |
| localhost | `/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies` | 200 | PASS | items=1 |
| localhost | `/api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap` | 200 | PASS | ok |
| localhost | `/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys` | 200 | PASS | ok |
| localhost | `/api/v1/stores/00000000-0000-0000-0000-000000000101` | 404 | **FAIL** | {"detail":"Not Found"} |
| 127.0.0.1 | `/health` | 200 | PASS | status=degraded db=up |
| 127.0.0.1 | `/dashboard/` | 200 | PASS | non-JSON |
| 127.0.0.1 | `/api/v1/stores/00000000-0000-0000-0000-000000000101/dashboard/summary` | 200 | PASS | non-JSON |
| 127.0.0.1 | `/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics` | 200 | PASS | series=0 |
| 127.0.0.1 | `/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel` | 200 | PASS | stages=4 visitors=0 |
| 127.0.0.1 | `/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies` | 200 | PASS | items=1 |
| 127.0.0.1 | `/api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap` | 200 | PASS | ok |
| 127.0.0.1 | `/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys` | 404 | **FAIL** | {"detail":"Not Found"} |
| 127.0.0.1 | `/api/v1/stores/00000000-0000-0000-0000-000000000101` | 404 | **FAIL** | {"detail":"Not Found"} |

## Failed requests

- `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101` → 404 — {"detail":"Not Found"}
- `http://127.0.0.1:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys` → 404 — {"detail":"Not Found"}
- `http://127.0.0.1:8000/api/v1/stores/00000000-0000-0000-0000-000000000101` → 404 — {"detail":"Not Found"}

## Dashboard fetch map (index.html)

| # | Method | Path | Auth | Required |
|---|--------|------|------|----------|
| 1 | GET | `/api/v1/stores/{store_id}/dashboard/summary` | X-API-Key | yes |
| 2 | GET | `/api/v1/stores/{store_id}/funnel` | X-API-Key | yes |
| 3 | GET | `/api/v1/stores/{store_id}/heatmap` | X-API-Key | yes |
| 4 | GET | `/api/v1/stores/{store_id}/metrics` | X-API-Key | yes |
| 5 | GET | `/api/v1/stores/{store_id}/anomalies` | X-API-Key | optional |
| 6 | GET | `/api/v1/stores/{store_id}/funnel/journeys` | X-API-Key | optional |
| 7 | GET | `/health` | none | optional |

## Root cause analysis

### Primary: API backend unavailable or erroring

The dashboard UI loads from `/dashboard/` (static HTML) but widgets call store analytics APIs.
When any **required** endpoint returns 401/404/500 or **hangs**, `refresh()` fails and KPI cards stay at `—`.

**Common causes:**
- Stale local `uvicorn` on port 8000 without PostgreSQL (HTTP 500 on all routes)
- Docker stack not running (`docker compose up -d`)
- Missing/wrong `X-API-Key` when `API_KEY_REQUIRED=true` (HTTP 401)
- Wrong store UUID (HTTP 404)
- No fetch timeout → hung server leaves UI on *Fetching live pipeline data…*

## Fixes applied

- `dashboard/index.html`: 15s fetch timeout; resilient optional endpoints; clearer 401/404 hints
- Run `docker compose up -d` before opening dashboard
- Use API key `purple-demo-key` (pre-filled in dashboard)

## Verification

```bash
docker compose up -d
python scripts/verify_dashboard_apis.py
python scripts/diagnose_dashboard.py
# open http://localhost:8000/dashboard/
```

