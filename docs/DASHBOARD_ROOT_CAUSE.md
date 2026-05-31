# Dashboard Data Loading — Root Cause Report

**Date:** 2026-05-30  
**Store:** `00000000-0000-0000-0000-000000000101`  
**Symptom:** KPI cards show `—`; `/api/v1/stores/{store_id}/anomalies` returns HTTP 500

---

## Executive summary

The dashboard UI is healthy. A **tuple-unpacking bug** in `AnomalyService._zone_summaries()` caused the anomalies API to crash. Because the dashboard loads all endpoints in a single `Promise.all()`, one 500 aborted the entire refresh and KPI values never updated from their placeholder `—`.

---

## 1. Exact backend exception

```
ValueError: too many values to unpack (expected 2)
```

**Location:** `app/services/anomaly_service.py`, line 170, inside `_zone_summaries()`

**Failing statement (Docker / pre-fix):**

```python
zone_key, zone_label = HeatmapService._resolve_zone(event.payload)
```

---

## 2. Full stack trace

```
ERROR: Exception in ASGI application
Traceback (most recent call last):
  File ".../uvicorn/protocols/http/httptools_impl.py", line 421, in run_asgi
    result = await app(...)
  File ".../fastapi/applications.py", line 1159, in __call__
    await super().__call__(scope, receive, send)
  File ".../starlette/middleware/errors.py", line 164, in __call__
    await self.app(scope, receive, _send)
  File "/srv/app/middleware/__init__.py", line 57, in dispatch
    response = await call_next(request)
  File ".../fastapi/routing.py", line 120, in app
    response = await f(request)
  File "/srv/app/routers/stores.py", line 86, in get_store_anomalies
    return await service.get_anomalies(store_id, from_ts=from_ts, to_ts=to_ts)
  File "/srv/app/services/anomaly_service.py", line 101, in get_anomalies
    current_zones = await self._zone_summaries(store_id, period_start, period_end)
  File "/srv/app/services/anomaly_service.py", line 170, in _zone_summaries
    zone_key, zone_label = HeatmapService._resolve_zone(event.payload)
ValueError: too many values to unpack (expected 2)
```

Captured from `docker logs smart-ai-storesurveillance-api-1` during a live request.

---

## 3. Failing query / service

| Layer | Component | Role |
|-------|-----------|------|
| **Router** | `GET /api/v1/stores/{store_id}/anomalies` | Entry point |
| **Service** | `AnomalyService.get_anomalies()` | Orchestrates zone + funnel baselines |
| **Failing method** | `AnomalyService._zone_summaries()` | Aggregates zone visit counts for anomaly rules |
| **Upstream call** | `HeatmapRepository.list_zone_events_in_period()` | Loads `vision.zone.entered` events (query succeeds) |
| **Root mismatch** | `HeatmapService._resolve_zone()` | Returns **3-tuple** `(zone_key, label, camera_zone_id)` |

The SQL/event query did not fail. The crash happened **after** events were loaded, while resolving zone keys from each event payload.

`HeatmapService._resolve_zone()` was extended to return a third value (`camera_zone_id`) for layout-aware heatmaps. `AnomalyService` still unpacked only two values.

---

## 4. Cascade to KPI cards

`dashboard/index.html` `refresh()` uses:

```javascript
const [summary, funnel, heatmap, metrics, anomalies, health] = await Promise.all([
  apiGet(`${base}/dashboard/summary`),
  apiGet(`${base}/funnel`),
  apiGet(`${base}/heatmap`),
  apiGet(`${base}/metrics`),
  apiGet(`${base}/anomalies`),   // ← throws on HTTP 500
  fetch("/health")...
]);
```

`apiGet()` throws on any non-2xx response. When anomalies returned 500, the `catch` block ran and KPI placeholders (`—`) were never replaced.

`dashboard/summary` also calls `get_anomalies()` internally, so it would fail the same way when hit directly from a stale container.

---

## 5. Fix applied

**File:** `app/services/anomaly_service.py`

```python
zone_key, zone_label, _ = HeatmapService._resolve_zone(event.payload)
```

The third return value (`camera_zone_id`) is intentionally ignored for anomaly zone aggregation.

**Deployment:** Rebuild the API Docker image so the running container picks up the fix:

```bash
docker compose up --build -d api
```

---

## 6. Verification

Run:

```bash
python scripts/verify_dashboard_apis.py
```

Expected: all endpoints return **HTTP 200** and KPI sample shows real values (e.g. `unique_visitors: 22`).

| Endpoint | Expected |
|----------|----------|
| `/health` | 200 |
| `…/dashboard/summary` | 200 + populated `kpis[]` |
| `…/funnel` | 200 |
| `…/heatmap` | 200 |
| `…/metrics` | 200 |
| `…/anomalies` | 200 |

---

## 7. Prevention

1. Keep `_resolve_zone` return shape consistent across `HeatmapService` and `AnomalyService`.
2. Add/keep integration test `tests/test_heatmap_anomaly_service.py::test_anomalies_api`.
3. Rebuild Docker after service-layer changes (`docker compose up --build`).
4. Optional hardening: use `Promise.allSettled` in the dashboard so one failing panel does not block KPI cards (not required once anomalies is fixed).
