# Visitor Metric Fix — Unique Visitors = COUNT(DISTINCT visitor_id)

**Date:** 2026-05-30  
**Store:** `00000000-0000-0000-0000-000000000101`

---

## Problem

The dashboard **Unique Visitors** KPI used **session count** from the funnel engine (`FunnelCalculator.unique_visitors`), not distinct vision track IDs from ingested events.

After the full YOLO run:

| Source | Count |
|--------|------:|
| Distinct `payload.external_track_id` in PostgreSQL | **22** |
| `sessions` rows | **1** |
| Dashboard / funnel API (before) | **1** |

---

## Fix

**Definition (now enforced):**

```
Unique Visitors = COUNT(DISTINCT payload.external_track_id)
```

- Customer events only (`class_label != staff`, `zone_type` not in `staff_only` / `ignore`)
- Applied in **`GET /funnel`** (`unique_visitors` field)
- Applied in **`GET /metrics`** (new `unique_visitors` + `session_count` fields)
- Dashboard KPI reads **`metrics.unique_visitors`** (fallback: `funnel.unique_visitors`)

**Code:**

| File | Change |
|------|--------|
| `app/domain/vision/visitor_count.py` | Shared SQL: distinct track IDs + session count |
| `app/services/funnel_service.py` | `unique_visitors` from events, not session calculator |
| `app/services/analytics_service.py` | Exposes `unique_visitors` on metrics response |
| `app/schemas/common.py` | `StoreMetricsResponse.unique_visitors`, `.session_count` |
| `dashboard/index.html` | KPI uses `metrics.unique_visitors` |

Funnel **stage counts** (ENTRY, ZONE_VISIT, etc.) remain **session-based** — only the headline visitor KPI changed.

---

## Before / After

| Metric | Before | After |
|--------|-------:|------:|
| DB distinct `external_track_id` | 22 | 22 |
| DB `sessions` | 1 | 1 |
| **`GET /funnel` → `unique_visitors`** | **1** | **22** |
| **`GET /metrics` → `unique_visitors`** | *(not exposed)* | **22** |
| **`GET /metrics` → `session_count`** | *(not exposed)* | **1** |
| **`dedupe_strategy`** | `external_track_id` / session mix | **`external_track_id`** |
| **Dashboard KPI `#kpiVisitors`** | **1** | **22** |

---

## Verification

```powershell
# Database ground truth
docker exec smart-ai-storesurveillance-postgres-1 psql -U si -d store_intelligence -c "
SELECT COUNT(DISTINCT payload->>'external_track_id') AS visitor_ids
FROM events WHERE payload->>'external_track_id' IS NOT NULL;
SELECT COUNT(*) AS sessions FROM sessions;
"

# API (requires X-API-Key)
curl -s -H "X-API-Key: purple-demo-key" \
  http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel \
  | jq '.unique_visitors, .meta.session_count'

curl -s -H "X-API-Key: purple-demo-key" \
  http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics \
  | jq '.unique_visitors, .session_count'
```

Open http://localhost:8000/dashboard/ — **Unique Visitors** should match DB distinct track count (**22**), not session count (**1**).

---

## Notes

- **22 track IDs ≠ 22 people** — ByteTrack/GIR fragmentation and same-frame over-merge can inflate IDs (see `docs/reid_audit_report.md`).
- **Session count (1)** remains available on metrics/funnel meta for funnel-stage analytics.
- Rebuild API after deploy: `docker compose up --build -d api`
