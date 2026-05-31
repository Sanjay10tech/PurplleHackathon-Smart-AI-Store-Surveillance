# Reviewer API Verification Report

**Generated:** 2026-05-31T08:50:27.141779+00:00  
**API base:** http://localhost:8000  
**Demo store:** `00000000-0000-0000-0000-000000000101`  
**API key:** `purple-demo-key` (header `X-API-Key`)

| Endpoint | URL | Auth | HTTP | Summary |
|----------|-----|------|------|---------|
| GET /health | `http://localhost:8000/health` | none | **200** ✓ | status=ok, db=up |
| GET /reviewer | `http://localhost:8000/reviewer` | none | **200** ✓ | checks=8/8, ready=True |
| GET /health/ready | `http://localhost:8000/health/ready` | none | **200** ✓ | ok |
| GET /metrics | `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics?metric=visitor.count` | X-API-Key | **200** ✓ | ok |
| GET /funnel | `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel` | X-API-Key | **200** ✓ | stages={'ENTRY': 3, 'ZONE_VISIT': 6, 'BILLING_QUEUE': 4, 'PURCHASE': 3} |
| GET /heatmap | `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap` | X-API-Key | **200** ✓ | zones=8, visits=32 |
| GET /anomalies | `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies` | X-API-Key | **200** ✓ | items=0 |
| GET /dashboard/summary | `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/dashboard/summary` | X-API-Key | **200** ✓ | kpis={'total_entries': 3, 'revenue': 34831.74, 'purchases': 24} |
| GET /funnel/journeys | `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys` | X-API-Key | **200** ✓ | journeys=11 |
| GET /reid/evidence | `http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/reid/evidence` | X-API-Key | **200** ✓ | cross_camera=2 |

## Curl quick-start

```bash
curl http://localhost:8000/health
curl http://localhost:8000/reviewer
curl -H "X-API-Key: purple-demo-key" "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics?metric=visitor.count"
curl -H "X-API-Key: purple-demo-key" "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel"
curl -H "X-API-Key: purple-demo-key" "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies"
```

**Result:** 10/10 endpoints returned HTTP 200
