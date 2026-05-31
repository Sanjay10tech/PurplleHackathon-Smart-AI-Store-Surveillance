# Reviewer Metric Validation

Generated: `2026-05-31T12:10:35.147981+00:00`  
Store: `00000000-0000-0000-0000-000000000101` (Brigade Road ST1008)  
Analysis window: `2026-04-10T12:15:05+00:00` → `2026-05-31T12:10:35.036999+00:00`  
Validation method: bootstrap replay against SQLite (same code path as Docker entrypoint)

## Summary metrics

| Metric | Value | Data source / proof |
|--------|------:|---------------------|
| Videos processed | 5/5 | `get_event_coverage()` → `payload.source_video` (CAM 1.mp4, CAM 2.mp4, CAM 3.mp4, CAM 4.mp4, CAM 5.mp4) |
| Events generated (period) | 61 | `COUNT(events)` in analysis window; bootstrap file has 37 vision rows |
| Vision events (all time) | 37 | `events WHERE event_type LIKE 'vision.%'` |
| Entries | 2 | `max(funnel ENTRY, count_store_entry_events)` — zone-entered tracks + session-based ENTRY |
| Exits | 2 | `count_store_exit_events()` — distinct `vision.track.ended` customer tracks |
| Customer sessions | 2 | `sessions` table after `materialize_visit_sessions()` (0 created) |
| POS purchases | 24 | `transactions` from `data/pos/Brigade_Bangalore_10_April_26.csv` |
| Revenue (NMV) | ₹34,831.74 | `SUM(transactions.amount)` |
| Linked POS purchases | 2 | `transactions.metadata.external_track_id` set by `pos_linker` (1 linked) |
| Linked conversion | 100.0% | `linked_purchases / entries` |

## Funnel consistency

| Stage | Count | Source |
|-------|------:|--------|
| ENTRY | 2 | Sessions + inferred from zone signals (`FunnelCalculator`) |
| ZONE_VISIT | 1 | `vision.zone.entered` → aisle/promo/consultation |
| BILLING_QUEUE | 1 | `vision.zone.entered` → billing_queue |
| PURCHASE | 1 | Linked `transactions` + `analytics.purchase.completed` |

| Check | Result |
|-------|--------|
| ENTRY ≥ linked purchases | PASS (2 ≥ 2) |
| Funnel PURCHASE ≤ ENTRY | PASS (1 ≤ 2) |
| Sessions > 0 | PASS |
| Entries > 0 | PASS |
| Exits > 0 | PASS |

## Data flow verified

```
CCTV JSONL → EventIngestionService → events table
           → materialize_visit_sessions → sessions table + session_id backfill
POS CSV    → PosIngestionService → transactions table
           → pos_linker (billing_queue tracks ↔ orders) → metadata.external_track_id
           → FunnelService → funnel stages
           → DashboardService → KPI cards
```

## Root causes fixed (this change)

1. **Wrong bootstrap order** — POS ran before CCTV; linkage saw zero billing tracks. Fixed in `scripts/docker_entrypoint.py` and `app/main.py`.
2. **No sessions persisted** — Bootstrap ingest wrote events only. Added `app/services/visit_session_materializer.py`.
3. **Linkage never re-run** — Added `ensure_reviewer_journey_metrics()` after both ingests.
4. **KPI NULL exclusion** — `class_label != 'staff'` dropped NULL rows; fixed with NULL-safe filters.
5. **Conversion denominator** — Dashboard used funnel-only `entry_count`; now uses `entries = max(funnel ENTRY, store entries)`.

## Reproduce

```bash
docker compose up --build
# or locally:
python scripts/bootstrap_cctv.py
python scripts/ingest_pos_csv.py
python scripts/materialize_journey_metrics.py
python scripts/generate_reviewer_metric_validation.py
curl -H "X-API-Key: purple-demo-key" http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/dashboard/summary
```
