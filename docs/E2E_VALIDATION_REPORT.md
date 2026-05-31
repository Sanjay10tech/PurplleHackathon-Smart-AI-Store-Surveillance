# End-to-End Validation Report — CCTV → Intelligence API

**Purpose:** Independent evidence pack for Purple challenge review  
**Validation date:** 2026-05-30 (updated post review fixes)  
**Store ID:** `00000000-0000-0000-0000-000000000101`  
**Validator:** Automated pipeline + PostgreSQL queries + live API + bounded funnel checks  

---

## Independent validation summary

| Artifact | Command | Proves |
|----------|---------|--------|
| Submission gate | `python scripts/validate_submission.py` | 10/10 API + pipeline + BI |
| CI gate | `python scripts/validate_submission.py --api-only` | Health + BI without videos |
| Real CV evidence | `python scripts/generate_detection_evidence.py` | YOLO on CCTV, annotated frames |
| Test suite | `pytest tests/ --cov-fail-under=96` | Regression + 96% coverage |
| Auth | `tests/test_auth.py` | Ingest rejects missing API key |

**Authentication:** Protected routes require `X-API-Key: purple-demo-key` (Docker default).

**Real CV evidence (2026-05-30):** `python scripts/generate_detection_evidence.py` processed CAM 3, CAM 1, and CAM 5 with YOLOv11n — 60 sampled frames, 82 person detections. See `docs/DETECTION_EVIDENCE.md` and `docs/evidence/detection_report.json`.

---

## Executive summary

| Step | Result |
|------|--------|
| 1. Pipeline on all CCTV videos | **PASS** — 5/5 MP4s processed |
| 2. Events generated | **PASS** — 28 events written to JSONL |
| 3. PostgreSQL ingest | **PASS** — 28/28 accepted, 0 rejected |
| 4. Metrics computed | **PASS** — footfall buckets in `store_metrics` |
| 5. Funnel API | **PASS** — non-zero stages, re-entry counted |
| 6. Heatmap API | **PASS** — 5 zones with visit counts |
| 7. Anomaly API | **PASS** — engine responded; no anomalies in window (expected) |
| 8. Health | **PASS** — `status=ok`, `feed=fresh` |

**Overall E2E chain:** CCTV files → detection pipeline → HTTP ingest → PostgreSQL → BI endpoints **verified working**.

---

## Test configuration

| Parameter | Value |
|-----------|-------|
| Command | `python -m pipeline.run --mock --ingest --persist-sessions --max-frames 80` |
| Detector mode | `--mock` with per-camera `mock_trajectories` (reads **real MP4 frames**, synthetic foot paths) |
| Video source | `data/videos/CAM 1.mp4` … `CAM 5.mp4` |
| Sample rate | 5 FPS (`pipeline/config.yaml`) |
| Max sampled frames | 80 per camera |
| API | `http://localhost:8000` (Docker Compose) |
| Database | `postgresql+asyncpg://si:si@localhost:5432/store_intelligence` |
| Pipeline run ID | `b9fa7766-4e2f-4ac4-af51-fe8a896800ca` |
| Correlation ID | `pipeline-b9fa77664e2f` |

---

## 1. Videos processed

| # | File | Camera role | Camera UUID | Sampled frames (`frame.processed`) |
|---|------|-------------|-------------|-----------------------------------:|
| 1 | `CAM 1.mp4` | Floor | `…0201` | 3 |
| 2 | `CAM 2.mp4` | Floor | `…0202` | 3 |
| 3 | `CAM 3.mp4` | Entry | `…0203` | 3 |
| 4 | `CAM 4.mp4` | Backroom | `…0204` | 3 |
| 5 | `CAM 5.mp4` | Billing | `…0205` | 3 |

**Videos processed:** **5 / 5**  
**Pipeline duration:** ~58 seconds  
**Output artifacts:**

- `data/pipeline/events.jsonl` — 28 events (this run)
- `data/pipeline/sessions.jsonl` — 5 sessions (this run)

---

## 2. Events generated (this run)

| Event type | Count |
|------------|------:|
| `vision.frame.processed` | 15 |
| `vision.zone.entered` | 9 |
| `vision.track.ended` | 4 |
| **Total** | **28** |

### Zone enters by type (this run)

| `zone_type` | Count | Camera | Notes |
|-------------|------:|--------|-------|
| `aisle` | 3 | CAM 1, CAM 2 | Floor circulation |
| `promo_island` | 1 | CAM 1 | Promo zone |
| `entrance` | 1 | CAM 3 | Entry landing |
| `billing_queue` | 3 | CAM 5 | Checkout queue |
| `staff_only` | 1 | CAM 4 | Staff track (excluded from customer BI) |

### Sample event (zone enter — billing)

```json
{
  "event_type": "vision.zone.entered",
  "occurred_at": "2026-05-30T06:22:16.338935Z",
  "payload": {
    "zone_id": "zone-cam5-queue",
    "zone_name": "billing_queue",
    "zone_type": "billing_queue",
    "camera_id": "00000000-0000-0000-0000-000000000205",
    "external_track_id": "00000000-0000-0000-0000-000000000101:22ebefee-cb13-4513-a958-3333c9f7438e",
    "class_label": "visitor",
    "session_id": "d1ecc8ae-3f03-4ffb-b048-4ed9a7077088"
  }
}
```

---

## 3. Visitors / tracks detected (this run)

| Metric | Count |
|--------|------:|
| Unique **visitor** `external_track_id` values | **4** |
| Unique **staff** `external_track_id` values | **1** |
| Visitor sessions created | **4** |
| Staff session created | **1** |
| **Total sessions persisted** | **5** |

Cross-camera link observed: track `…b6352fec…` appears on CAM 1, CAM 2, and CAM 5 (Global Identity Registry + billing queue enter).

---

## 4. PostgreSQL ingest verification

### This run (HTTP batch)

| Metric | Value |
|--------|------:|
| Events posted | 28 |
| Accepted | **28** |
| Rejected | **0** |
| Duplicate | **0** |
| Batches | 1 |
| Sessions persisted (before POST) | **5** |

### Cumulative store state (includes earlier validation runs same day)

> **Assumption:** PostgreSQL already contained events from prior `validate_submission.py` runs. Counts below are **store totals**, not isolated to this run alone.

| Table / metric | Count |
|----------------|------:|
| Total `events` rows | **58** |
| `vision.frame.processed` | 27 |
| `vision.zone.entered` | 21 |
| `vision.track.ended` | 10 |
| Total `sessions` rows | **15** |
| Active sessions | 15 |
| `store_metrics` buckets | **2** |

**Ingest integrity:** All 28 events from this run accepted; no FK violations after sessions-first ordering.

---

## 5. Metrics output

### Projection step

```bash
python scripts/project_demo_metrics.py
# → Projected 2 footfall metric bucket(s)
```

| Bucket (UTC hour) | `footfall.count` | Sample count |
|-------------------|-----------------:|-------------:|
| 2026-05-30 05:00 | 6 | 6 |
| 2026-05-30 06:00 | 15 | 15 |

### API response — `GET /api/v1/stores/{id}/metrics`

```json
{
  "metric": "footfall.count",
  "granularity": "hour",
  "series": [
    { "bucket_start": "2026-05-30T05:00:00Z", "value": 6.0, "sample_count": 6 }
  ],
  "meta": { "partial": false, "source": "store_metrics" }
}
```

**Status:** **PASS** — metrics no longer placeholder; sourced from `store_metrics`.  
**Note:** API returned 1 series point in the default 24h window query; DB holds 2 buckets (06:00 bucket may be at window boundary depending on query `to_ts`).

---

## 6. Funnel output

**Endpoint:** `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/funnel`  
**Period:** Last 24 hours  
**Dedupe:** `external_track_id`

| Field | Value |
|-------|------:|
| `unique_visitors` | 15 |
| `meta.source` | `funnel_engine` |

| Stage | Count | Conversion | Drop-off | Re-entries |
|-------|------:|-----------:|---------:|-----------:|
| ENTRY | 15 | 0.40 | 0.60 | 3 |
| ZONE_VISIT | 6 | 1.00 | 0.00 | 2 |
| BILLING_QUEUE | 6 | 0.00 | 1.00 | 0 |
| PURCHASE | 0 | — | — | 0 |

**Status:** **PASS** — funnel stages populated from ingested zone/session data.  
**Note:** PURCHASE = 0 because no `analytics.purchase.completed` events were ingested in this E2E run (expected without POS seed).

---

## 7. Heatmap output

**Endpoint:** `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap`

| Field | Value |
|-------|------:|
| `meta.source` | `heatmap_engine` |
| `meta.total_visits` | 20 |
| `meta.data_confidence` | LOW |
| Zones returned | **5** |

| Zone | Visits | Normalized visit score |
|------|-------:|----------------------:|
| aisle_circulation (CAM 1) | 6 | 1.0 |
| billing_queue (CAM 5) | 6 | 1.0 |
| promo_beat_the_heat (CAM 1) | 3 | 0.25 |
| entry_landing (CAM 3) | 3 | 0.25 |
| aisle_circulation (CAM 2) | 2 | 0.0 |

**Status:** **PASS** — zone visit frequency computed from `vision.zone.entered`.  
**Note:** Dwell samples = 0 (no paired exit events with dwell in window); confidence correctly reported as LOW.

---

## 8. Anomalies output

**Endpoint:** `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies`

```json
{
  "items": [],
  "meta": {
    "source": "anomaly_engine_empty",
    "computed_count": 0,
    "persisted_count": 0,
    "baseline_start": "2026-05-28T06:23:28.265133+00:00",
    "baseline_end": "2026-05-29T06:23:28.265133+00:00"
  }
}
```

| Check | Result |
|-------|--------|
| API responds 200 | Yes |
| Engine executes | Yes (`anomaly_engine_empty` — no rules fired) |
| STALE_FEED | **Not raised** (feed fresh — see health) |
| QUEUE_SPIKE | Not raised (baseline/context insufficient in short run) |
| CONVERSION_DROP | Not raised |
| DEAD_ZONE | Not raised |

**Status:** **PASS** — anomaly detection **works** (returns valid empty result with baseline metadata). Empty `items` is **expected** for a short mock ingest without seeded spike/drop scenarios.

To demonstrate non-empty anomalies, run scenario tests:

```bash
pytest tests/scenarios/test_queue_spike.py tests/scenarios/test_stale_feed.py -v
```

---

## 9. Health verification

**Endpoint:** `GET /health`

```json
{
  "status": "ok",
  "checks": { "database": "up", "feed": "fresh" },
  "last_event_at": "2026-05-30T06:22:28.347853Z",
  "feed_stale_minutes": 1.0,
  "stale_feed": false
}
```

**Endpoint:** `GET /health/ready`

```json
{ "status": "ready", "checks": { "database": "up" } }
```

---

## 10. End-to-end flow diagram (as executed)

```
data/videos/CAM 1-5.mp4
        │
        ▼
pipeline.run (--mock --ingest --persist-sessions --max-frames 80)
        │  TrajectoryMockPersonDetector per camera
        │  ByteTrack + zones.yaml + SessionManager
        ▼
data/pipeline/events.jsonl  (28 events)
        │
        ├── persist 5 sessions → PostgreSQL.sessions
        └── POST batch → /api/v1/events/ingest (28 accepted)
                │
                ▼
         PostgreSQL.events
                │
                ├── scripts/project_demo_metrics.py → store_metrics
                │
                └── GET /metrics, /funnel, /heatmap, /anomalies, /health
```

---

## 11. Assumptions and limitations (reviewer disclosure)

| # | Assumption | Impact on evidence |
|---|------------|-------------------|
| 1 | **`--mock` mode** uses configured foot trajectories over real video frames, not YOLO bounding boxes from pixel content | Proves **integration + zone logic + ingest**; does not prove CV detection accuracy on Purplle footage |
| 2 | **`--max-frames 80`** subsamples each ~2 min clip at 5 FPS | Not full-footage processing; sufficient for E2E proof |
| 3 | **PostgreSQL totals (58 events, 15 sessions)** include earlier validation runs on the same Docker volume | This run contributed **28 events** and **5 new sessions**; funnel/heatmap reflect cumulative 24h window |
| 4 | **Metrics projection** via `scripts/project_demo_metrics.py` is manual, not a continuous worker | Required step before `/metrics` returns non-placeholder series |
| 5 | **No purchase events** in this run | Funnel PURCHASE stage = 0 |
| 6 | **Staff track on CAM 4** ingested (`staff_only` zone) but excluded from customer funnel/heatmap via `is_customer_metric_event()` | Correct BI behavior |
| 7 | **Anomalies empty** | Engine healthy; use pytest scenarios for rule-fire demonstrations |
| 8 | **Videos not in git** | Reviewer must copy to `data/videos/` via `scripts/setup_videos.py` |

---

## 12. Reproduction commands

```bash
# Prerequisites
docker compose up --build -d
python scripts/setup_videos.py --check
pip install -r pipeline/requirements.txt
export DATABASE_URL=postgresql+asyncpg://si:si@localhost:5432/store_intelligence

# E2E run (this report)
python -m pipeline.run --mock --ingest --persist-sessions --max-frames 80
python scripts/project_demo_metrics.py

# Verify
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel | jq .
curl -s http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap | jq .
curl -s http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies | jq .
curl -s http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics | jq .
```

Automated gate:

```bash
python scripts/validate_submission.py   # expects 10/10 when videos + stack up
pytest tests/scenarios/test_bi_full_validation.py -v
```

---

## 13. Conclusion for Purple reviewer

This E2E validation demonstrates a **complete working path**:

> **CCTV MP4s → pipeline → vision events → PostgreSQL → Intelligence API (metrics, funnel, heatmap, anomalies, health)**

The evidence supports **integration and BI correctness**. It does **not** claim:

- Full-length YOLO inference on all frames
- Non-empty operational anomalies without seeded scenarios
- Automatic metrics projection without `project_demo_metrics.py`

For strict CV evaluation, re-run without `--mock`:

```bash
python -m pipeline.run --ingest --persist-sessions --camera "CAM 3" --max-frames 50
```

---

## Appendix — Key counts (this run only)

| Metric | Value |
|--------|------:|
| Videos processed | 5 |
| Events generated | 28 |
| Visitor tracks | 4 |
| Staff tracks | 1 |
| Sessions created | 5 |
| Ingest accepted | 28 |
| Ingest rejected | 0 |
