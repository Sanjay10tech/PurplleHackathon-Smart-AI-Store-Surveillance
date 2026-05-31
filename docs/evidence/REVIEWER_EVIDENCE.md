# Reviewer Evidence — Purple Tech Round 2

**Generated:** 2026-05-30T21:53:25.227467+00:00

## Acceptance Gate

| Check | Status | Evidence |
|-------|--------|----------|
| docker compose up | PASS | api + postgres healthy on :8000 / :5432 |
| API availability | PASS | GET /api/v1/stores/{id}/dashboard/summary |
| Event generation | PASS | 121 events |
| DESIGN.md | PASS | docs/DESIGN.md |
| CHOICES.md | PASS | docs/CHOICES.md |
| Stability | PASS | API healthcheck passing |

## Detection

- Entries: 3 (CAM 3 entry_threshold line, mock + YOLO)
- Exits: 1 (fixed: CAM 3 dwell trajectory clears 2s line debounce)
- Re-entries: 0
- Queue events: 5 (CAM 5 billing_queue)
- Videos contributing: 5/5

## API

- Dashboard exits KPI: 1 (matches DB: 1)
- Dashboard visitors KPI: 9
- Funnel ENTRY: 3
- Funnel PURCHASE: 0 (POS: 24 txns — session link pending)
- `/api/v1/stores/{id}/funnel` — FunnelCalculator session dedupe
- `/api/v1/stores/{id}/anomalies` — rule engine on real events
- `/api/v1/stores/{id}/heatmap` — zone.entered aggregation

## Production

- Docker: docker-compose.yml (api, postgres, pipeline-worker profile)
- Tests: pytest suite including test_dashboard_metrics_audit.py
- Observability: structured logs, health endpoint

## Layout Validation

- Duplicate layout file (unused): data\store_layout\Brigade_Road_Layout.xlsx.xlsx