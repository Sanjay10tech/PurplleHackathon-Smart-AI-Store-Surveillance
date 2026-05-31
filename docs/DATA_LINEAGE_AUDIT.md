# End-to-End Data Lineage Audit — Store Intelligence Dashboard

**Audit date:** 2026-05-30  
**Dashboard URL:** http://localhost:8000/dashboard/  
**Demo store:** `00000000-0000-0000-0000-000000000101`  
**Auditor:** Senior engineering review (code + live PostgreSQL + API)

---

## Executive summary

| Question | Answer |
|----------|--------|
| What powers the dashboard **right now** (localhost Docker)? | **Mock trajectory detection** on **real CCTV MP4 frames**, ingested via `validate_submission.py` → PostgreSQL |
| Is data from real YOLO on video in the DB? | **No** (unless you manually run `pipeline.run` without `--mock --ingest`) |
| Are `data/samples/events/*.json` loaded into the DB? | **No** (test/reference files only) |
| What is seeded at Docker boot? | **Store + tenant only** — no analytics events |

**Live DB snapshot (this audit):**

| Table / metric | Count |
|----------------|------:|
| `events` (total) | **84** |
| `events` · `vision.frame.processed` | 39 |
| `events` · `vision.zone.entered` | 29 |
| `events` · `vision.track.ended` | 16 |
| `sessions` | **17** |
| `store_metrics` | **4** |
| `anomalies` (persisted rows) | **0** |

**File artifacts (not auto-loaded to DB):**

| Artifact | Events | Purpose |
|----------|-------:|---------|
| `data/pipeline/events.jsonl` | **4** | Last local pipeline JSONL export |
| `data/samples/events/*.json` | **6** | Reference / test ingest payloads |
| `docs/evidence/sample_events.json` | **4** | YOLO evidence bundle (copied samples) |
| Real YOLO on CCTV (`generate_detection_evidence.py`) | **82 detections** (images only) | Offline CV proof — **not ingested to DB** |

---

## Master lineage diagram

```
data/videos/CAM {1-5}.mp4          Real CCTV files (~680 MB, gitignored)
        │
        ▼
pipeline/run.py  process_camera_video()          pipeline/run.py:55-110
        │
        ├─ [--mock]  TrajectoryMockPersonDetector   pipeline/detect.py:28-59, 191-206
        │             (synthetic foot paths from pipeline/config.yaml mock_trajectories)
        │
        └─ [default] YoloV11PersonDetector          pipeline/detect.py:84-164
                      (real person boxes — NOT used by validate_submission)
        │
        ▼
MultiCameraPipeline.process_frame()               pipeline/tracker.py
        │  ByteTrack + zone lines/polygons          pipeline/zones.yaml
        │  SessionManager + staff heuristics
        │
        ▼
EventBuilder → vision.frame.processed             pipeline/emit.py:43-80
               vision.zone.entered/exited          pipeline/emit.py (zone_event)
               vision.track.ended                   pipeline/emit.py (track_ended)
        │
        ▼
EventEmitter.flush() → POST /api/v1/events/ingest pipeline/emit.py + pipeline/ingest.py
        │              (--persist-sessions → sessions table)
        ▼
PostgreSQL
  events          app/models/event.py
  sessions        app/models/visit_session.py
  store_metrics   app/models/store_metric.py  ← MetricsProjectorService
        │
        ▼
FastAPI services
  FunnelService   GET /api/v1/stores/{id}/funnel
  HeatmapService  GET /api/v1/stores/{id}/heatmap
  AnalyticsService GET /api/v1/stores/{id}/metrics
  AnomalyService  GET /api/v1/stores/{id}/anomalies
        │
        ▼
dashboard/index.html  (fetch + Chart.js, 5s poll)
```

---

## Per-metric lineage

### 1. Unique Visitors

| Step | Detail |
|------|--------|
| **Dashboard** | `#kpiVisitors` ← `funnel.unique_visitors` |
| **Code** | `dashboard/index.html` · `refresh()` · `animateValue(..., funnel.unique_visitors)` |
| **API** | `GET /api/v1/stores/{id}/funnel` → `StoreFunnelResponse.unique_visitors` |
| **Service** | `FunnelService.get_funnel()` → `FunnelCalculator.compute()` |
| **Logic** | Count of deduplicated visitor keys from `sessions` rows in 24h window (`external_track_id` or `session_id`) |
| **Repository** | `FunnelRepository.list_sessions_in_period()` → table **`sessions`** |
| **Upstream events** | Sessions created when pipeline runs with `--persist-sessions`; linked to `vision.zone.entered` via `session_id` on events |
| **Live value** | **17** |

**SOURCE:** **Mock data** (trajectory overlay on real MP4) → sessions persisted from pipeline ingest. **Not** real YOLO boxes. **Not** sample JSON files.

**Evidence:**
- Session query: `app/repositories/funnel_repository.py:16-32`
- Calculator: `app/domain/funnel/calculator.py:48-88`
- Ingest trigger: `scripts/validate_submission.py:92-105` (`--mock --persist-sessions`)

---

### 2. Conversion Rate

| Step | Detail |
|------|--------|
| **Dashboard** | `#kpiConversion` ← `PURCHASE` stage `conversion_rate`, else `purchaseCount/entryCount` |
| **Code** | `dashboard/index.html` · `stageRate(funnel.stages, "PURCHASE")` |
| **API** | Same funnel endpoint |
| **Service** | `FunnelCalculator._build_metrics()` caps rate at 100% |
| **Logic** | Stage-to-stage conversion: `min(next_count, count) / count` for ENTRY→ZONE_VISIT→BILLING_QUEUE→PURCHASE |
| **DB inputs** | `sessions` + `events` (`vision.zone.entered` with mapped `zone_type`) + `transactions` |
| **Live value** | **35.3%** (ENTRY→ZONE_VISIT); PURCHASE stage **0%** (0 purchases) |

**SOURCE:** **Mock pipeline events** driving zone stages. No real purchase/POS data in demo DB.

**Evidence:**
- Rate cap: `app/domain/funnel/calculator.py:123-126`
- Zone mapping: `app/domain/funnel/stages.py:19-30`
- Funnel events query: `app/repositories/funnel_repository.py:34-55`

---

### 3. Queue Depth

| Step | Detail |
|------|--------|
| **Dashboard** | `#kpiQueue` ← `stageCount(funnel.stages, "BILLING_QUEUE")` |
| **Code** | `dashboard/index.html` · `refresh()` |
| **API** | Funnel endpoint · stage `BILLING_QUEUE` |
| **Logic** | Visitors who triggered `vision.zone.entered` with `zone_type` mapped to `BILLING_QUEUE` (`billing_queue`, `checkout`, `queue`, `billing`) |
| **Pipeline origin** | Mock trajectory crosses billing zone lines in `pipeline/zones.yaml` (CAM 5 billing_queue) |
| **Live value** | **6** |

**SOURCE:** **Mock data** — synthetic foot path enters billing zones on real video frames.

**Evidence:**
- Default zone mapping: `app/domain/funnel/stages.py:26-29`
- Mock trajectories CAM 5: `pipeline/config.yaml:61-66`
- Queue trend chart: client-side history buffer in `dashboard/index.html` (not stored in DB)

---

### 4. Anomaly Count

| Step | Detail |
|------|--------|
| **Dashboard** | `#kpiAnomalies` ← `anomalies.items.length` |
| **Code** | `dashboard/index.html` · `apiGet(.../anomalies)` |
| **API** | `GET /api/v1/stores/{id}/anomalies` |
| **Service** | `AnomalyService.get_anomalies()` — **computed on read** from funnel + heatmap + feed timestamps |
| **Rules** | QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, STALE_FEED (`app/domain/anomaly/detector.py`) |
| **Persisted rows** | `anomalies` table — **0 rows** in live DB |
| **Live value** | **1** (computed, not persisted) |

**SOURCE:** **Derived from mock-ingested events** + on-read rule engine. Not from sample files.

**Evidence:**
- On-read engine: `app/services/anomaly_service.py:79-153`
- Dashboard: `dashboard/index.html` · `anomalyCount = (anomalies.items \|\| []).length`

---

### 5. Funnel (table + chart)

| Step | Detail |
|------|--------|
| **Dashboard** | Funnel table `#funnel` + bar chart `#funnelChart` |
| **API** | `GET /api/v1/stores/{id}/funnel` |
| **Stages** | ENTRY · ZONE_VISIT · BILLING_QUEUE · PURCHASE |
| **DB** | `sessions` + session-linked `vision.zone.entered` + `transactions` |

**Live stages:**

| Stage | Count | Conversion |
|-------|------:|-----------:|
| ENTRY | 17 | 35.3% |
| ZONE_VISIT | 6 | 100% |
| BILLING_QUEUE | 6 | 0% |
| PURCHASE | 0 | — |

**SOURCE:** **Mock pipeline** on real CCTV MP4s.

**Evidence:**
- Service docstring: `app/services/funnel_service.py:1-34`
- Dashboard render: `renderFunnelTable()` · `updateFunnelChart()` in `dashboard/index.html`

---

### 6. Heatmap (table + zone grid)

| Step | Detail |
|------|--------|
| **Dashboard** | `#heatmap` table + `#heatmapViz` color grid |
| **API** | `GET /api/v1/stores/{id}/heatmap` |
| **Service** | `HeatmapService.get_heatmap()` |
| **DB** | `events` where `event_type IN ('vision.zone.entered', 'vision.zone.exited')` |
| **Calculator** | `HeatmapCalculator.compute()` — visit counts, dwell, normalized scores |

**SOURCE:** **Mock-generated `vision.zone.entered`** events from trajectory crossing zone polygons/lines.

**Evidence:**
- Repository: `app/repositories/heatmap_repository.py:16-33`
- Service: `app/services/heatmap_service.py:49-75`
- Zone config: `pipeline/zones.yaml`

---

### 7. Visitor trend chart (metrics)

| Step | Detail |
|------|--------|
| **Dashboard** | `#visitorChart` ← `metrics.series[].value` |
| **API** | `GET /api/v1/stores/{id}/metrics?metric=footfall.count` |
| **Service** | `AnalyticsService.get_metrics()` |
| **DB** | **`store_metrics`** table (pre-aggregated hourly buckets) |
| **Projector** | `MetricsProjectorService.project_footfall()` counts customer `vision.zone.entered` per hour |

**SOURCE:** **Mock zone-enter events** → projector → `store_metrics`. **4 buckets** in live DB.

**Evidence:**
- Projector: `app/services/metrics_projector_service.py:31-68`
- Analytics read: `app/services/analytics_service.py:54-82`
- Validation projector step: `scripts/validate_submission.py:120-135`

---

## Source classification matrix

| Data path | Classification | Reaches dashboard DB? |
|-----------|----------------|----------------------|
| `data/videos/CAM *.mp4` | **Real CCTV video files** | Yes — as frame input only |
| `pipeline.run --mock` + `mock_trajectories` | **Mock detection** on real frames | **Yes** (primary path) |
| `pipeline.run` (YOLO, no `--mock`) | **Real CCTV analysis** | Only if manually run with `--ingest` |
| `scripts/generate_detection_evidence.py` | **Real YOLO** (annotated JPGs) | **No** — evidence only |
| `data/samples/events/*.json` | **Sample events** (synthetic builder) | **No** — tests / manual ingest |
| `data/pipeline/events.jsonl` | Pipeline export artifact | **No** — file only |
| `scripts/seed_dev_data.py` | **Seeded data** (store/tenant) | Store row only, no events |
| `tests/helpers/seed.py` | **Test mock events** | SQLite test DB only |
| `AnomalyService` on-read rules | **Computed** from ingested events | Yes (derived) |
| Queue trend chart (client buffer) | **Client-side mock history** | Not in DB |

---

## Event volume evidence

### A. Events from videos (mock pipeline → PostgreSQL)

**Primary ingest command** (runs during `validate_submission.py`):

```bash
python -m pipeline.run --mock --ingest --persist-sessions --camera "CAM 3" --max-frames 50
# repeated for CAM 1, CAM 5
```

| File | Role |
|------|------|
| `scripts/validate_submission.py:92-105` | Orchestrates 3-camera mock ingest |
| `pipeline/run.py:148-149` | Sets `detector.mode = mock` |
| `pipeline/detect.py:191-206` | Per-camera `TrajectoryMockPersonDetector` |
| `pipeline/config.yaml:37-66` | Foot paths per camera |
| `pipeline/emit.py` | Builds + POSTs events |

**Estimated events per validation run:** ~15–25 accepted events per camera (varies by zone crossings); **accumulated 84 total** in DB after multiple runs (new `pipeline_run_id` per run; idempotency keys include run id).

**Detection mode truth table:**

| Mode | Reads MP4 pixels? | Person location source | Used by validate_submission? |
|------|-------------------|------------------------|------------------------------|
| `--mock` + trajectories | Yes | Config foot points | **Yes** |
| `--mock` (no trajectories) | Yes | Fixed center bbox | No (trajectories configured) |
| YOLO (default config) | Yes | YOLOv11n inference | **No** |

### B. Events from sample files

| File | Events | Loaded to prod DB? |
|------|-------:|--------------------|
| `data/samples/events/vision.frame.processed.json` | 1 | No |
| `data/samples/events/vision.zone.entered.json` | 1 | No |
| `data/samples/events/vision.zone.exited.json` | 1 | No |
| `data/samples/events/batch_ingest.json` | 3 | No |
| **Total** | **6** | **No** (used in `tests/scenarios/test_pipeline_e2e.py`) |

Generated by: `EventEmitter.write_sample_files()` · `pipeline/emit.py:266-400`  
Or: `pipeline.run --write-samples` · `pipeline/run.py:155-161`

### C. Mock / synthetic events (non-video)

| Source | Count | DB? |
|--------|------:|-----|
| Trajectory mock on video (classified as mock detection) | **84 in live `events`** | Yes |
| Pytest `tests/helpers/seed.py` | Hundreds in CI SQLite | Test only |
| `EventEmitter.write_sample_files()` static builder | 6 on disk | No |

### D. Real YOLO evidence (offline)

| Artifact | Quantity | In PostgreSQL? |
|----------|----------|----------------|
| `docs/evidence/annotated/*.jpg` | 60 frames | No |
| YOLO person detections | **82** total (CAM 3/1/5) | No |
| `docs/evidence/detection_report.json` | Report | No |
| `docs/evidence/sample_events.json` | 4 sample JSON docs | No |

Script: `scripts/generate_detection_evidence.py` — runs **real** `YoloV11PersonDetector` for images; pipeline sample uses `--write-samples` without `--ingest`.

---

## Seeded vs computed vs ingested

| Layer | What is seeded | Code |
|-------|----------------|------|
| Docker boot | Tenant `default`, store `…0101` | `scripts/docker_entrypoint.py:38-40` → `scripts/seed_dev_data.py` |
| Docker boot | **No events, sessions, or metrics** | — |
| After validation | Sessions + events from mock pipeline | `validate_submission.py` |
| After ingest | `store_metrics` via projector | `app/services/metrics_projector_service.py` |
| On API read | Anomalies computed live | `app/services/anomaly_service.py` |

---

## Dashboard → API mapping (code locations)

| UI element | API | Dashboard JS |
|------------|-----|--------------|
| Unique Visitors | `/funnel` | `kpiVisitors` · line ~820 |
| Conversion Rate | `/funnel` | `kpiConversion` · line ~824 |
| Queue Depth | `/funnel` · `BILLING_QUEUE` | `kpiQueue` · line ~828 |
| Anomaly Count | `/anomalies` | `kpiAnomalies` · line ~831 |
| Funnel table/chart | `/funnel` | `renderFunnelTable` · `updateFunnelChart` |
| Heatmap table/grid | `/heatmap` | `renderHeatmapTable` · `renderHeatmapViz` |
| Visitor trend | `/metrics` | `updateVisitorChart` |
| Queue trend | `/funnel` (client history) | `updateQueueChart` |

All fetches: `dashboard/index.html` · `apiGet()` · header `X-API-Key` · 5s `setInterval(refresh, 5000)`.

---

## Honest disclosure for Purple reviewers

1. **Dashboard numbers are real relative to the database** — they are not hard-coded in the UI.
2. **Database events are predominantly mock-trajectory pipeline output** reading real MP4 files, not YOLO inference.
3. **Real YOLO proof exists offline** (`docs/DETECTION_EVIDENCE.md`) but is a **separate path** from the live dashboard data unless you run:
   ```bash
   python -m pipeline.run --ingest --persist-sessions --camera "CAM 3" --max-frames 100
   ```
   (without `--mock`)
4. **Sample JSON files are documentation/test artifacts** — not auto-loaded at startup.

---

## Verification commands

```bash
# Live DB event breakdown
docker exec smart-ai-storesurveillance-postgres-1 psql -U si -d store_intelligence \
  -c "SELECT event_type, COUNT(*) FROM events GROUP BY event_type;"

# Live API values (same as dashboard)
curl -s -H "X-API-Key: purple-demo-key" \
  http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel | jq '.unique_visitors, .stages'

# Count sample file events
python -c "import json; from pathlib import Path; print(sum(len(json.loads(p.read_text()).get('events',[json.loads(p.read_text())])) if 'batch' in p.name else 1) for p in Path('data/samples/events').glob('*.json')))"
```

---

## Audit conclusion

| Metric | Ultimate source for current dashboard |
|--------|---------------------------------------|
| Unique Visitors | Mock pipeline sessions → **`sessions`** |
| Conversion Rate | Mock zone events → **funnel calculator** |
| Queue Depth | Mock billing zone crossings → **funnel BILLING_QUEUE** |
| Anomaly Count | **Computed** from mock-ingested data |
| Funnel | Same as above |
| Heatmap | Mock **`vision.zone.entered`** events |
| Visitor trend | Projected **`store_metrics`** from mock zone enters |

**To show real YOLO lineage on the dashboard:** run the pipeline without `--mock`, with `--ingest --persist-sessions`, then refresh http://localhost:8000/dashboard/.
