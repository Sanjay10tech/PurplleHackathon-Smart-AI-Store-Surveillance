# Dashboard Health Report

**Date:** 2026-05-30  
**Store:** `00000000-0000-0000-0000-000000000101`  
**Symptom:** UI loads; KPI cards show `—`; status stuck on *Fetching live pipeline data…*

---

## Root cause (exact)

The dashboard HTML loads from `/dashboard/` (static). Widgets depend on `refresh()` calling store analytics APIs in parallel. **Any required endpoint failure or hang aborts the entire refresh**, so `applyKpiValues()` never runs and cards stay at `—`. With no fetch timeout, a hung backend leaves the status text on *Fetching live pipeline data…* indefinitely.

Contributing factors (often combined):

| # | Cause | Effect |
|---|--------|--------|
| 1 | **Backend:** `AnomalyService._zone_summaries()` unpacked 2 values from a 3-tuple | `/anomalies` → HTTP **500** |
| 2 | **Frontend:** `Promise.all` + `apiGet()` throws on HTTP ≥ 400 | One bad endpoint blocks all KPIs |
| 3 | **Environment:** Stale local `uvicorn` on `127.0.0.1:8000` without Postgres | HTTP **500** / hung requests |
| 4 | **Environment:** Docker not running; old process owns port 8000 | Same as above |
| 5 | **Dual listener:** `localhost` → Docker; `127.0.0.1` → stale dev server | Journeys **404** on IPv4-only path |
| 6 | **No pipeline ingest** | KPIs valid but **0** (`meta.partial=true`) — not empty `—` if refresh succeeds |
| 7 | **Docker image stale** | Frontend fixes not live until `docker compose up --build -d api` |

---

## API audit (dashboard `refresh()`)

| # | Method | Path | Auth | Required |
|---|--------|------|------|----------|
| 1 | GET | `/api/v1/stores/{store_id}/dashboard/summary` | X-API-Key | yes |
| 2 | GET | `/api/v1/stores/{store_id}/funnel` | X-API-Key | yes |
| 3 | GET | `/api/v1/stores/{store_id}/heatmap` | X-API-Key | yes |
| 4 | GET | `/api/v1/stores/{store_id}/metrics` | X-API-Key | yes |
| 5 | GET | `/api/v1/stores/{store_id}/anomalies` | X-API-Key | optional (after fix) |
| 6 | GET | `/api/v1/stores/{store_id}/funnel/journeys` | X-API-Key | optional |
| 7 | GET | `/health` | none | optional |

### Verified paths (user checklist)

| Path | Expected | Actual (`localhost:8000`) |
|------|----------|---------------------------|
| `/health` | 200 | **200** (status=degraded when no recent ingest) |
| `/metrics` | N/A at root | **404** — use `/api/v1/stores/{id}/metrics` |
| `/funnel` | N/A at root | **404** — use `/api/v1/stores/{id}/funnel` |
| `/anomalies` | N/A at root | **404** — use `/api/v1/stores/{id}/anomalies` |
| `/dashboard/` | 200 HTML | **200** |
| `/api/v1/stores/{store_id}` | no route | **404** (no bare store GET) |

All store-scoped dashboard endpoints → **200** on `http://localhost:8000` with `X-API-Key: purple-demo-key`.

---

## Auth & store_id

| Test | HTTP | Detail |
|------|------|--------|
| No `X-API-Key` | **401** | Unauthorized |
| Wrong key | **401** | Unauthorized |
| Wrong store UUID | **404** | Store not found |
| Demo store + key | **200** | 18 KPIs, values 0 without ingest |

---

## Fixes applied

### Backend — `app/services/anomaly_service.py`

```python
zone_key, zone_label, _ = HeatmapService._resolve_zone(event.payload)
```

### Frontend — `dashboard/index.html`

- 15s `fetchWithTimeout()` via `AbortController`
- `loadEndpoint()` — anomalies + journeys non-fatal
- Clear 401/404 hints; timeout message suggests `docker compose up -d`
- Error panel in `#kpiSections` when refresh fails

### Tooling

- `scripts/diagnose_dashboard.py` → `DASHBOARD_DEBUG_REPORT.md`
- `scripts/verify_dashboard_apis.py` — uses `localhost:8000`

---

## Verification

```bash
docker compose up --build -d
python scripts/verify_dashboard_apis.py
python scripts/diagnose_dashboard.py
# Open http://localhost:8000/dashboard/  (prefer localhost over 127.0.0.1)
# API key: purple-demo-key (pre-filled)
# Store ID: 00000000-0000-0000-0000-000000000101
```

**Expected after fix:** KPI cards show **0** (not `—`); status shows *Partial data* until pipeline ingest. Charts/funnel tables populate with zeros.

**Non-zero KPIs:** run pipeline worker (`docker compose --profile full up pipeline-worker`) or ingest events manually.

---

## Files changed

| File | Change |
|------|--------|
| `app/services/anomaly_service.py` | 3-tuple unpack fix |
| `dashboard/index.html` | Timeout, resilient refresh, error UX |
| `scripts/diagnose_dashboard.py` | Full endpoint audit script |
| `scripts/verify_dashboard_apis.py` | localhost base URL |
| `tests/test_heatmap_anomaly_service.py` | Regression test |
