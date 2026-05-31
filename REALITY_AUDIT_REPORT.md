# Reality Audit Report — Dashboard KPI Lineage

**Generated:** 2026-05-30T20:12:17.197285+00:00
**Store ID:** `00000000-0000-0000-0000-000000000101`
**Analysis window:** 2026-05-29T20:12:13.731282+00:00 → 2026-05-30T20:12:13.731282+00:00 (default last 24h)

## Executive verdict

| Question | Answer |
|----------|--------|
| Is data from real YOLO CCTV inference? | **No** — current DB events are from **`--mock` trajectory pipeline** on real MP4 files |
| Is data seeded/fake in SQL? | **No** — rows are append-only ingested `events`; only `stores` demo row is seeded |
| Is dashboard using hardcoded KPI numbers? | **No** — all KPIs computed from SQL aggregations at request time |
| Detector mode in DB | `mock` |
| Overall classification | **MOCK pipeline** |

## Pipeline vs dashboard reconciliation

| Metric | Pipeline run | Database | Dashboard | Notes |
|--------|-------------|----------|-----------|-------|
| Videos processed | 3 (CAM 1, 3, 5 × 50 frames) | 3 cameras in events | provenance | Mock ingest via `python -m pipeline.run --mock --ingest` |
| Frames sampled | 150 | 7 `vision.frame.processed` rows | — | Frame events emitted every `emit_frame_events_every_n=30` sampled frames only |
| Detections | embedded in frame events | 7 detection objects in JSON | — | Not a dashboard KPI |
| Generated events | 13 (4+5+4 per camera run) | 16 | pipeline_events=16 | ✅ Match |
| Unique tracks | 3 global IDs | SQL=4 | unique_visitors=4 | ✅ Match |
| Zone enters | 4 customer zone enters | SQL=5 | zone_visits=5 | ✅ Match |
| Customer sessions | 1 (CAM 3 entry only) | SQL=2 | customer_sessions=2 | Sessions created only on `is_store_entry` (CAM 3 entry_threshold) |

### Mismatch explanations

1. **150 frames vs 6 frame events** — Pipeline samples 50 frames/camera but emits `vision.frame.processed` only every 30th sampled frame (`processing.emit_frame_events_every_n: 30`). Zone/track events are sparse by design.
2. **3 unique visitors vs 1 session** — Each camera mock run creates a distinct `external_track_id`. Only CAM 3 crosses `entry_threshold` → one persisted `sessions` row. CAM 1/5 tracks contribute zone events but not store-entry sessions.
3. **No `detector_mode` on legacy rows** — Events ingested before the lineage stamp lack payload metadata; classification inferred from ingest command (`--mock`). Re-ingest with updated emitter to stamp `detector_mode` + `source_video`.
4. **Footfall chart empty** — `store_metrics` has projected buckets only after projector runs; chart uses placeholder until enough hourly buckets exist.
5. **Anomalies are derived rules** — Computed on-read from funnel/heatmap baselines, not raw CCTV counts.

## Table row counts

| Table | Rows | Role |
|-------|-----:|------|
| `events` | 16 | Ingested pipeline + vision events (source of truth) |
| `sessions` | 2 | Visit sessions from entry threshold |
| `transactions` | 0 | POS purchases (empty unless linked) |
| `stores` | 1 | Demo store seed only |
| `anomalies` | 0 | Persisted anomalies (optional) |
| `store_metrics` | 2 | Projected footfall time series |

## Per-metric audit

### Unique Visitors

| Field | Detail |
|-------|--------|
| Dashboard value | **4** |
| SQL recomputed | **4** (✅ Match) |
| Classification | **MOCK pipeline → **derived** distinct track count** |

1. **SQL query**

```sql
SELECT COUNT(DISTINCT payload->>'external_track_id')
FROM events
WHERE store_id = :store AND occurred_at BETWEEN :from AND :to
  AND payload->>'external_track_id' IS NOT NULL
  AND lower(coalesce(payload->>'class_label','')) != 'staff'
  AND lower(coalesce(payload->>'zone_type','')) NOT IN ('staff_only','ignore')
```

2. **Source table:** `events` (16 total rows in table)
3. **CCTV videos:** CAM 1.mp4, CAM 3.mp4, CAM 5.mp4 (via mock trajectories)
4. **Contributing events:** - `vision.frame.processed` @ 2026-05-30T19:43:38.417232+00:00 cam=CAM 3.mp4 track=None
- `vision.track.ended` @ 2026-05-30T19:43:38.617432+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:96b6326a-e5bb-4ecf-b6a5-359fa0953a1a
- `vision.zone.entered` @ 2026-05-30T19:43:39.618432+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:96b6326a-e5bb-4ecf-b6a5-359fa0953a1a
- `vision.frame.processed` @ 2026-05-30T19:43:44.423232+00:00 cam=CAM 3.mp4 track=None
- `vision.frame.processed` @ 2026-05-30T19:44:45.265579+00:00 cam=CAM 1.mp4 track=None
- `vision.zone.entered` @ 2026-05-30T19:44:45.265579+00:00 cam=CAM 1.mp4 track=00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca
- `vision.track.ended` @ 2026-05-30T19:44:45.465779+00:00 cam=CAM 1.mp4 track=00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca
- `vision.zone.entered` @ 2026-05-30T19:44:46.266579+00:00 cam=CAM 1.mp4 track=00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca
- `vision.frame.processed` @ 2026-05-30T19:44:51.271579+00:00 cam=CAM 1.mp4 track=None
- `vision.frame.processed` @ 2026-05-30T19:45:18.558109+00:00 cam=CAM 5.mp4 track=None
- `vision.zone.entered` @ 2026-05-30T19:45:18.558109+00:00 cam=CAM 5.mp4 track=00000000-0000-0000-0000-000000000101:507176b4-fb2b-4d95-949e-96880f625e7e
- `vision.track.ended` @ 2026-05-30T19:45:18.758258+00:00 cam=CAM 5.mp4 track=00000000-0000-0000-0000-000000000101:507176b4-fb2b-4d95-949e-96880f625e7e
- `vision.frame.processed` @ 2026-05-30T19:45:24.562568+00:00 cam=CAM 5.mp4 track=None
- `vision.frame.processed` @ 2026-05-30T20:10:13.949063+00:00 cam=CAM 3.mp4 track=None
- `vision.track.ended` @ 2026-05-30T20:10:14.149263+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:9fc191d6-6f52-4883-bdce-bd9543743847
- `vision.zone.entered` @ 2026-05-30T20:10:15.150263+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:9fc191d6-6f52-4883-bdce-bd9543743847
5. **Data class:** MOCK pipeline → **derived** distinct track count
6. **Hardcoded logic:** None — computed in `visitor_count.count_distinct_visitor_ids()`
7. **Date filter:** `occurred_at BETWEEN '2026-05-29T20:12:13.731282+00:00' AND '2026-05-30T20:12:13.731282+00:00'` (default last 24h if query params omitted)
8. **Store filter:** `store_id = '00000000-0000-0000-0000-000000000101'`
9. **Dedupe:** Distinct on `external_track_id`; staff/ignore zones excluded


### Total Entries

| Field | Detail |
|-------|--------|
| Dashboard value | **2** |
| SQL recomputed | **2** (✅ Match) |
| Classification | **MOCK pipeline** |

1. **SQL query**

```sql
SELECT COUNT(*) FROM events
WHERE store_id = :store AND event_type = 'vision.zone.entered'
  AND payload->>'is_store_entry' IN ('true','True','1')
```

2. **Source table:** `events` (16 total rows in table)
3. **CCTV videos:** CAM 3.mp4 only (entry_threshold zone on entry camera)
4. **Contributing events:** Rows where `is_store_entry=true` (typically one CAM 3 crossing)
5. **Data class:** MOCK pipeline
6. **Hardcoded logic:** Entry flag set in `EventBuilder.zone_event()` when zone_type in (entry_threshold, entrance)
7. **Date filter:** `occurred_at BETWEEN '2026-05-29T20:12:13.731282+00:00' AND '2026-05-30T20:12:13.731282+00:00'` (default last 24h if query params omitted)
8. **Store filter:** `store_id = '00000000-0000-0000-0000-000000000101'`
9. **Dedupe:** None at SQL layer; zone debounce in pipeline


### Total Exits

| Field | Detail |
|-------|--------|
| Dashboard value | **0** |
| SQL recomputed | **0** (✅ Match) |
| Classification | **MOCK pipeline** |

1. **SQL query**

```sql
SELECT COUNT(*) FROM events
WHERE event_type IN ('vision.zone.entered','vision.zone.exited')
  AND payload->>'is_store_exit' IN ('true','True','1')
```

2. **Source table:** `events` (16 total rows in table)
3. **CCTV videos:** None in current mock run (no exit threshold crossed)
4. **Contributing events:** Zero rows with `is_store_exit=true`
5. **Data class:** MOCK pipeline
6. **Hardcoded logic:** Exit flag from pipeline zone transition
7. **Date filter:** `occurred_at BETWEEN '2026-05-29T20:12:13.731282+00:00' AND '2026-05-30T20:12:13.731282+00:00'` (default last 24h if query params omitted)
8. **Store filter:** `store_id = '00000000-0000-0000-0000-000000000101'`
9. **Dedupe:** Pipeline line debounce


### Re-Entries

| Field | Detail |
|-------|--------|
| Dashboard value | **3** |
| SQL recomputed | **3** (✅ Match) |
| Classification | ****derived** from funnel calculator + event flags** |

1. **SQL query**

```sql
Dashboard uses MAX(event reentry count, funnel re_entry sum)
Event SQL: COUNT(*) WHERE payload->>'is_reentry' = true
```

2. **Source table:** `events + funnel engine` (16 total rows in table)
3. **CCTV videos:** All cameras (funnel stage re-touches)
4. **Contributing events:** Funnel `re_entry_count` aggregated across stages
5. **Data class:** **derived** from funnel calculator + event flags
6. **Hardcoded logic:** `re_entries = max(reentry_events, funnel_reentries)` in dashboard_service
7. **Date filter:** `occurred_at BETWEEN '2026-05-29T20:12:13.731282+00:00' AND '2026-05-30T20:12:13.731282+00:00'` (default last 24h if query params omitted)
8. **Store filter:** `store_id = '00000000-0000-0000-0000-000000000101'`
9. **Dedupe:** First-touch funnel — re-entries increment stage re_entry_count not stage count


### Sessions (Customer Sessions KPI)

| Field | Detail |
|-------|--------|
| Dashboard value | **2** |
| SQL recomputed | **2** (✅ Match) |
| Classification | **MOCK pipeline → persisted session from pipeline `--persist-sessions`** |

1. **SQL query**

```sql
SELECT COUNT(*) FROM sessions
WHERE store_id = :store AND started_at BETWEEN :from AND :to
  AND coalesce(metadata->>'staff','false') NOT IN ('true','True','1')
```

2. **Source table:** `sessions` (2 total rows in table)
3. **CCTV videos:** CAM 3.mp4 (entry session creation)
4. **Contributing events:** 1 session row linked to CAM 3 entry track
5. **Data class:** MOCK pipeline → persisted session from pipeline `--persist-sessions`
6. **Hardcoded logic:** Funnel meta `session_count` = customer sessions in period
7. **Date filter:** `sessions.started_at` in window
8. **Store filter:** `store_id = '00000000-0000-0000-0000-000000000101'`
9. **Dedupe:** Session merge within 45s (`session.merge_active_within_seconds`)


### Zone Visits

| Field | Detail |
|-------|--------|
| Dashboard value | **5** |
| SQL recomputed | **5** (✅ Match) |
| Classification | ****derived** via HeatmapCalculator from zone enter events** |

1. **SQL query**

```sql
Heatmap engine: COUNT customer vision.zone.entered per zone, SUM visit_count
Raw SQL equivalent: COUNT(*) FROM events WHERE event_type='vision.zone.entered' AND customer filter
```

2. **Source table:** `events` (16 total rows in table)
3. **CCTV videos:** CAM 1, 3, 5 — one zone enter each (+ CAM 1 second zone)
4. **Contributing events:** - `vision.frame.processed` @ 2026-05-30T19:43:38.417232+00:00 cam=CAM 3.mp4 track=None
- `vision.track.ended` @ 2026-05-30T19:43:38.617432+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:96b6326a-e5bb-4ecf-b6a5-359fa0953a1a
- `vision.zone.entered` @ 2026-05-30T19:43:39.618432+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:96b6326a-e5bb-4ecf-b6a5-359fa0953a1a
- `vision.frame.processed` @ 2026-05-30T19:43:44.423232+00:00 cam=CAM 3.mp4 track=None
- `vision.frame.processed` @ 2026-05-30T19:44:45.265579+00:00 cam=CAM 1.mp4 track=None
- `vision.zone.entered` @ 2026-05-30T19:44:45.265579+00:00 cam=CAM 1.mp4 track=00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca
- `vision.track.ended` @ 2026-05-30T19:44:45.465779+00:00 cam=CAM 1.mp4 track=00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca
- `vision.zone.entered` @ 2026-05-30T19:44:46.266579+00:00 cam=CAM 1.mp4 track=00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca
- `vision.frame.processed` @ 2026-05-30T19:44:51.271579+00:00 cam=CAM 1.mp4 track=None
- `vision.frame.processed` @ 2026-05-30T19:45:18.558109+00:00 cam=CAM 5.mp4 track=None
- `vision.zone.entered` @ 2026-05-30T19:45:18.558109+00:00 cam=CAM 5.mp4 track=00000000-0000-0000-0000-000000000101:507176b4-fb2b-4d95-949e-96880f625e7e
- `vision.track.ended` @ 2026-05-30T19:45:18.758258+00:00 cam=CAM 5.mp4 track=00000000-0000-0000-0000-000000000101:507176b4-fb2b-4d95-949e-96880f625e7e
- `vision.frame.processed` @ 2026-05-30T19:45:24.562568+00:00 cam=CAM 5.mp4 track=None
- `vision.frame.processed` @ 2026-05-30T20:10:13.949063+00:00 cam=CAM 3.mp4 track=None
- `vision.track.ended` @ 2026-05-30T20:10:14.149263+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:9fc191d6-6f52-4883-bdce-bd9543743847
- `vision.zone.entered` @ 2026-05-30T20:10:15.150263+00:00 cam=CAM 3.mp4 track=00000000-0000-0000-0000-000000000101:9fc191d6-6f52-4883-bdce-bd9543743847
5. **Data class:** **derived** via HeatmapCalculator from zone enter events
6. **Hardcoded logic:** Dashboard reads `heatmap.meta.total_visits`
7. **Date filter:** `occurred_at BETWEEN '2026-05-29T20:12:13.731282+00:00' AND '2026-05-30T20:12:13.731282+00:00'` (default last 24h if query params omitted)
8. **Store filter:** `store_id = '00000000-0000-0000-0000-000000000101'`
9. **Dedupe:** Staff/ignore filtered; layout remap optional


### Funnel

Computed in-memory by `FunnelCalculator` from `sessions` + `events` + `transactions`.

**Source tables:** `sessions`, `events` (zone enter + purchase events), `transactions`

- ENTRY: count=2 re_entry=2
- ZONE_VISIT: count=1 re_entry=1
- BILLING_QUEUE: count=1 re_entry=0
- PURCHASE: count=0 re_entry=0

- **Classification:** derived / first-touch funnel
- **Hardcoded:** stage order ENTRY→ZONE_VISIT→BILLING_QUEUE→PURCHASE in `FUNNEL_STAGE_ORDER`
- **Date filter:** sessions by `started_at`; events by `occurred_at`
- **Dedupe:** `external_track_id` visitor keys; re-entries don't increase stage count

### Heatmap

- **Zones returned:** 4
- **Total visits (meta):** 5
- **Source:** `events` where type in (vision.zone.entered, vision.zone.exited)
- **Classification:** derived normalization (0–1 scores), not raw CCTV pixels
- **Layout remap:** Brigade Road YAML when configured

### Anomalies

- **Items shown:** 0
- **Source:** on-read rule engine (`AnomalyDetector`) + optional `anomalies` table
- **Classification:** **derived** — QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, STALE_FEED
- **Not direct CCTV counts** — compares current vs baseline window

## Event inventory (all rows)

| Time | Type | Camera / Video | Track | Flags |
|------|------|----------------|-------|-------|
| 2026-05-30T19:43:38.417232+00:00 | vision.frame.processed | CAM 3.mp4 | `None` | — |
| 2026-05-30T19:43:38.617432+00:00 | vision.track.ended | CAM 3.mp4 | `00000000-0000-0000-0000-000000000101:96b6326a-e5bb-4ecf-b6a5-359fa0953a1a` | — |
| 2026-05-30T19:43:39.618432+00:00 | vision.zone.entered | CAM 3.mp4 | `00000000-0000-0000-0000-000000000101:96b6326a-e5bb-4ecf-b6a5-359fa0953a1a` | ENTRY, entry_threshold |
| 2026-05-30T19:43:44.423232+00:00 | vision.frame.processed | CAM 3.mp4 | `None` | — |
| 2026-05-30T19:44:45.265579+00:00 | vision.frame.processed | CAM 1.mp4 | `None` | — |
| 2026-05-30T19:44:45.265579+00:00 | vision.zone.entered | CAM 1.mp4 | `00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca` | aisle |
| 2026-05-30T19:44:45.465779+00:00 | vision.track.ended | CAM 1.mp4 | `00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca` | — |
| 2026-05-30T19:44:46.266579+00:00 | vision.zone.entered | CAM 1.mp4 | `00000000-0000-0000-0000-000000000101:800c2c90-bad3-4188-85c5-eab72693d5ca` | promo_island |
| 2026-05-30T19:44:51.271579+00:00 | vision.frame.processed | CAM 1.mp4 | `None` | — |
| 2026-05-30T19:45:18.558109+00:00 | vision.frame.processed | CAM 5.mp4 | `None` | — |
| 2026-05-30T19:45:18.558109+00:00 | vision.zone.entered | CAM 5.mp4 | `00000000-0000-0000-0000-000000000101:507176b4-fb2b-4d95-949e-96880f625e7e` | billing_queue |
| 2026-05-30T19:45:18.758258+00:00 | vision.track.ended | CAM 5.mp4 | `00000000-0000-0000-0000-000000000101:507176b4-fb2b-4d95-949e-96880f625e7e` | — |
| 2026-05-30T19:45:24.562568+00:00 | vision.frame.processed | CAM 5.mp4 | `None` | — |
| 2026-05-30T20:10:13.949063+00:00 | vision.frame.processed | CAM 3.mp4 | `None` | — |
| 2026-05-30T20:10:14.149263+00:00 | vision.track.ended | CAM 3.mp4 | `00000000-0000-0000-0000-000000000101:9fc191d6-6f52-4883-bdce-bd9543743847` | — |
| 2026-05-30T20:10:15.150263+00:00 | vision.zone.entered | CAM 3.mp4 | `00000000-0000-0000-0000-000000000101:9fc191d6-6f52-4883-bdce-bd9543743847` | ENTRY, entry_threshold |

## Recommendations

## Fix applied — dashboard lineage transparency

| Item | Before | After (re-ingest with updated emitter) |
|------|--------|----------------------------------------|
| `payload.detector_mode` | `null` on legacy rows | `mock` or `yolo` stamped on every event |
| `payload.source_video` | absent | path to MP4 on frame events |
| Dashboard provenance bar | no detector label | **Detector: MOCK/YOLO** + video filenames |
| KPI SQL logic | unchanged | unchanged — still 100% from `events`/`sessions` |

After CAM 3 re-ingest (10 frames): events **13 → 16**, unique_visitors **3 → 4**, sessions **1 → 2**.

## Recommendations

1. **For real YOLO proof:** re-run without `--mock`:
   `python -m pipeline.run --ingest --persist-sessions --camera "CAM 3" --max-frames 50`
2. **Re-ingest** to stamp `detector_mode` + `source_video` on all payloads (fix applied in `pipeline/emit.py`).
3. **Dashboard provenance bar** now surfaces detector mode and source videos when present.
4. **Do not treat mock trajectory runs as production CCTV accuracy** — they validate ingest/funnel wiring only.

## Verification commands

```bash
python scripts/generate_reality_audit_report.py
python scripts/verify_dashboard_apis.py
```
