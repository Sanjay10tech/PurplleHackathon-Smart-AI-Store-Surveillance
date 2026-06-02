# Store Intelligence

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-24292e?logo=github)](CI_SETUP.md)

Turn CCTV footage and POS orders into retail analytics: footfall, zone heatmaps, conversion funnels, linked purchase journeys, and operational anomalies. Phase 1 ships a FastAPI backend, PostgreSQL storage, an offline YOLOv11 + ByteTrack pipeline, and a live dashboard fed by ingested events — not hardcoded KPIs.

**Round 2 reviewer entry point:** [docs/REVIEWER_EVIDENCE.md](./docs/REVIEWER_EVIDENCE.md) · [docs/REVIEWER_API.md](./docs/REVIEWER_API.md)
<img width="1337" height="670" alt="Screenshot 2026-06-02 141815" src="https://github.com/user-attachments/assets/c023f69e-f8fb-4b3c-94e0-66c7f2754d9a" />
<img width="1340" height="684" alt="Screenshot 2026-06-02 141834" src="https://github.com/user-attachments/assets/baadcc43-3eb9-4a32-bbf5-9875edd1cb12" />

<img width="1350" height="675" alt="Screenshot 2026-06-02 141852" src="https://github.com/user-attachments/assets/307335b3-eb16-4eab-b70c-5bed1d2a70fe" />
<img width="1344" height="676" alt="Screenshot 2026-06-02 141913" src="https://github.com/user-attachments/assets/a0b096ba-f236-4eb0-aa7f-b308866aa4d1" />
<img width="1341" height="659" alt="Screenshot 2026-06-02 141931" src="https://github.com/user-attachments/assets/3f14a058-bc9f-4eec-bcdb-b6daeb63c757" />
<img width="1344" height="669" alt="Screenshot 2026-06-02 141947" src="https://github.com/user-attachments/assets/d3743e25-6a3e-4812-bd85-9bd6167f907d" />
<img width="1347" height="666" alt="Screenshot 2026-06-02 142001" src="https://github.com/user-attachments/assets/8e0f720f-3c36-418c-9258-3636c31248cb" />
<img width="1348" height="668" alt="Screenshot 2026-06-02 142018" src="https://github.com/user-attachments/assets/b6fa5100-f84c-4d21-a763-d6ff441ff56d" />
<img width="897" height="205" alt="Screenshot 2026-06-02 142033" src="https://github.com/user-attachments/assets/6842db5b-b9b4-4e59-be86-61d15feb1ac1" />

---

## CCTV Video Assets

The CCTV video files are not included in this submission package due to the HackerEarth 50 MB upload limit.

Download the challenge video assets from:

https://drive.google.com/drive/folders/1GtSXGw57IrmYLRxBfecaBvt6_zfSTBNe?usp=drive_link

Place all downloaded video files inside:

data/videos/

Expected files:

* CAM1.mp4
* CAM2.mp4
* CAM3.mp4
* CAM4.mp4
* CAM5.mp4

After placing the files, run:

docker compose up

The pipeline will automatically discover and process all available CCTV videos.


## Project Overview

Store Intelligence answers: *How many shoppers entered, where did they go, how many reached billing, and how many purchased?*

| Layer | What it does |
|-------|----------------|
| **Detection pipeline** (`pipeline/`) | Reads Brigade Road CCTV MP4s, runs YOLOv11 + ByteTrack, emits `vision.*` events |
| **Ingest API** | Validates, deduplicates, and persists events to PostgreSQL |
| **Analytics engines** | Funnel, heatmap, anomalies, metrics — computed on read from stored events |
| **Dashboard** | Live UI at `/dashboard/` calling authenticated store APIs |
| **POS linkage** | Brigade Bangalore CSV orders ingested as `transactions`; linker matches CCTV billing tracks |

**Phase 1 (implemented):** REST API, ingest, BI engines, dashboard, WebSocket feed, Docker Compose, CI, real-YOLO pipeline path, reviewer bootstrap data.

**Phase 2 (not deployed):** Redis Streams, MinIO frame storage, distributed GPU fleet, JWT auth, Kubernetes.

---

## Architecture Summary

Hexagonal layout: **routers → services → repositories → PostgreSQL**, with pure domain logic in `app/domain/`.

```
CCTV MP4s / bootstrap JSONL  →  pipeline/run.py  →  POST /events/ingest
POS CSV                    →  ingest_pos_csv.py →  transactions table
                                                      ↓
                                              events + sessions
                                                      ↓
                    GET /stores/{id}/funnel | heatmap | metrics | anomalies | dashboard/summary
                                                      ↓
                                              dashboard/index.html
```

On `docker compose up`, the API container automatically: migrates DB, seeds demo store, bootstraps committed YOLO vision events (if DB empty), ingests POS CSV, and materializes journey metrics. Optional `pipeline-worker` re-processes all five MP4s with live YOLO when videos are mounted.

See [DESIGN.md](./DESIGN.md) for diagrams, data flow, and scaling notes.

---

## Repository Structure

```
app/
├── domain/           # Pure calculators: funnel, heatmap, anomaly, POS linker, visitor count
├── routers/          # HTTP endpoints (health, events, stores, reviewer, ws)
├── services/         # Orchestration (FunnelService, DashboardService, …)
├── repositories/     # SQLAlchemy queries
├── models/           # ORM (events, sessions, transactions, store_metrics, …)
├── schemas/          # Pydantic DTOs
└── middleware/       # Trace IDs, structured logging

pipeline/             # Offline CV: detect.py, tracker.py, emit.py, run.py, config.yaml
dashboard/            # Static live dashboard (Chart.js, calls store APIs)
scripts/              # Docker entrypoint, validation, reviewer setup, evidence generators
tests/                # Unit, service, scenario, and E2E tests
data/
├── videos/           # CCTV MP4s (not in git — use setup_videos.py)
├── pos/              # Brigade POS CSV (committed sample)
└── reviewer/         # Committed YOLO bootstrap event JSONL for instant demo
alembic/              # Database migrations
DESIGN.md             # System design (submission)
CHOICES.md            # Engineering decisions (submission)
```

---

## Prerequisites

| Requirement | Version / notes |
|-------------|-----------------|
| **Docker + Docker Compose** | Recommended for reviewers (API + Postgres) |
| **Python** | 3.11+ (local dev and pipeline) |
| **PostgreSQL** | 16 (via Compose or local) |
| **Git** | Clone repository |
| **CCTV videos (optional)** | Five MP4s under `data/videos/` for live YOLO re-ingest (~680 MB, not in git) |
| **GPU (optional)** | Speeds YOLO; CPU works with small frame counts |

---

## Installation

### Docker (recommended)

```bash
git clone <repository-url>
cd Smart-AI-StoreSurveillance
docker compose up --build
```

No manual seeding required. Wait until http://localhost:8000/health returns `"status": "ok"`.

### Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

docker compose up postgres -d
alembic upgrade head
python scripts/seed_dev_data.py
python scripts/bootstrap_cctv.py          # optional if not using Docker entrypoint
python scripts/ingest_pos_csv.py          # optional
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Copy `.env.example` to `.env` to override defaults.

---

## How to Run

```bash
docker compose up --build
```

| URL | Purpose |
|-----|---------|
| http://localhost:8000/dashboard/ | Live dashboard |
| http://localhost:8000/docs | OpenAPI / Swagger UI |
| http://localhost:8000/health | Liveness + DB + feed freshness |
| http://localhost:8000/reviewer | Public 8-check proof checklist |
| http://localhost:8000/reviewer/api | Machine-readable reviewer API guide |

Stop: `docker compose down` · Wipe DB: `docker compose down -v`

**Optional live YOLO on all five cameras** (requires MP4s in `data/videos/`):

```bash
docker compose --profile full up --build
```

The `pipeline-worker` service runs real YOLO (`PIPELINE_MODE=yolo` by default), not mock.

---

## How to Run Detection Pipeline

Videos must exist under `data/videos/` (see `data/videos/README.md`).

```bash
pip install -e ".[pipeline]"
python scripts/setup_videos.py --source "/path/to/CCTV Footage"   # once per machine
python scripts/setup_videos.py --check

# Real YOLO (default):
export DATABASE_URL=postgresql+asyncpg://si:si@localhost:5432/store_intelligence
export API_KEY=purple-demo-key
python -m pipeline.run --ingest --persist-sessions --camera "CAM 3" --max-frames 50

# All discovered videos:
python -m pipeline.run --ingest --persist-sessions --all-videos --max-frames 50

# Mock trajectories (dev/CI shortcut only — not real detection):
python -m pipeline.run --mock --ingest --persist-sessions --camera "CAM 3" --max-frames 50
```

Post-ingest projection:

```bash
python scripts/project_demo_metrics.py
python scripts/materialize_journey_metrics.py
```

Validation:

```bash
python scripts/validate_submission.py           # full: real YOLO + BI (when videos present)
python scripts/validate_submission.py --api-only   # 7/7 API checks (CI mode)
python scripts/validate_submission.py --mock      # mock trajectories instead of YOLO
```

Configuration: `pipeline/config.yaml`, `pipeline/zones.yaml`.

---

## How to Run Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib
pytest tests/scenarios/ -v
```

| Metric | Value |
|--------|-------|
| **Tests** | **280** collected (`pytest tests/ --co -q`) |
| **Coverage gate** | **≥ 96%** branch coverage on `app/` (CI + `pyproject.toml`) |
| **Last CI run** | See [CI_EVIDENCE.md](./CI_EVIDENCE.md) |

One-command reviewer setup:

```bash
./scripts/setup_reviewer.sh          # Linux/macOS
.\scripts\reviewer_setup.ps1       # Windows
```

---

## API Documentation

Interactive docs: **http://localhost:8000/docs**

Protected routes require header **`X-API-Key: purple-demo-key`** when `API_KEY_REQUIRED=true` (Docker default). In **`REVIEWER_MODE=true`**, the demo key is always accepted.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Process health, DB, feed freshness |
| GET | `/health/ready` | Readiness probe |
| GET | `/reviewer` | Public proof checklist |
| POST | `/api/v1/events/ingest` | Single or batch event ingest (max 500) |
| GET | `/api/v1/stores/{store_id}/metrics` | Footfall / visitor time series |
| GET | `/api/v1/stores/{store_id}/funnel` | Conversion funnel stages |
| GET | `/api/v1/stores/{store_id}/funnel/journeys` | Linked CCTV → POS journeys |
| GET | `/api/v1/stores/{store_id}/heatmap` | Zone visits and dwell |
| GET | `/api/v1/stores/{store_id}/anomalies` | Queue spike, conversion drop, dead zone, stale feed |
| GET | `/api/v1/stores/{store_id}/dashboard/summary` | Aggregated KPIs for dashboard |
| GET | `/api/v1/stores/{store_id}/reid/evidence` | Cross-camera Re-ID evidence |
| WS | `/ws/stores/{store_id}/live` | Live funnel/heatmap/metrics snapshots |

Sample ingest body:

```json
{
  "event_type": "vision.zone.entered",
  "occurred_at": "2026-05-30T12:00:00Z",
  "store_id": "00000000-0000-0000-0000-000000000101",
  "aggregate": { "type": "zone", "id": "00000000-0000-0000-0000-000000000001" },
  "payload": { "zone_type": "browse", "external_track_id": "store:track-1" },
  "idempotency_key": "demo-zone-enter-1"
}
```

---

## Dashboard URL

**http://localhost:8000/dashboard/**

Pre-filled **Store ID** and **API Key**. Hard refresh (`Ctrl+Shift+R`) after API restart.

The dashboard reads PostgreSQL via store APIs. KPI cards are computed at request time from ingested events — not static demo numbers.

**Understanding dashboard data (important for reviewers):**

| Signal | Meaning |
|--------|---------|
| **Vision events** | Count of rows in `events` for the analysis window |
| **CCTV videos** | Distinct cameras / MP4s represented in ingested events |
| **Funnel purchase** | Visitors who reached PURCHASE stage via CCTV+POS linkage (often **1** in demo) |
| **POS purchases** | All completed orders from CSV (**24** in demo) — not all are CCTV-linked |
| **Feed: stale / batch** | Expected after bootstrap or batch ingest — not a live RTSP feed |

See [docs/POS_CCTV_LINKAGE.md](./docs/POS_CCTV_LINKAGE.md) and [REALITY_AUDIT_REPORT.md](./REALITY_AUDIT_REPORT.md).

---

## Health Endpoint

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
```

Returns DB connectivity, global feed status, and `STALE_FEED` when no recent `vision.*` events (default threshold: 15 minutes, `HEALTH_STALE_FEED_MINUTES`).

---

## Metrics Endpoint

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics?metric=footfall.count&granularity=hour"
```

Returns hourly buckets from `store_metrics` when projected; falls back to aggregating `vision.zone.entered` events directly.

---

## Funnel Endpoint

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel"
```

Stages: **ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE**. Includes `conversion_rate`, `drop_off_rate`, and `re_entry_count` per stage. See [Retail business story](#retail-business-story) below.

Optional query params: `from_ts`, `to_ts` (ISO-8601). Default window spans **first ingested event → now** when called from dashboard summary path; direct funnel API defaults to last 24h unless overridden.

---

## Heatmap Endpoint

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap"
```

Per-zone `visit_count`, average dwell (from exit events), normalized scores, and optional Brigade Road layout mapping.

---

## Anomalies Endpoint

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies"
```

On-read rule engine: **QUEUE_SPIKE**, **CONVERSION_DROP**, **DEAD_ZONE**, **STALE_FEED**. Compares current window to equal-length baseline immediately before the query window.

---

## Store ID

```
00000000-0000-0000-0000-000000000101
```

Seeded automatically on first boot (`scripts/seed_dev_data.py` via Docker entrypoint).

---

## API Key

```
purple-demo-key
```

Send as header: `X-API-Key: purple-demo-key`

Docker Compose defaults: `API_KEY=purple-demo-key`, `API_KEY_REQUIRED=true`, `REVIEWER_MODE=true`.

---

## Sample Reviewer Flow

1. **Start stack**
   ```bash
   docker compose up --build
   ```
2. **Verify health**
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/reviewer
   ```
3. **Open dashboard** — http://localhost:8000/dashboard/  
   Confirm KPIs populate (vision events, funnel stages, heatmap zones).
4. **Call BI APIs** (copy-paste from [docs/REVIEWER_API.md](./docs/REVIEWER_API.md))
5. **Optional — real YOLO refresh**
   ```bash
   python scripts/setup_videos.py --source "/path/to/CCTV Footage"
   docker compose --profile full up pipeline-worker --build
   ```
6. **Run validation**
   ```bash
   python scripts/validate_submission.py --api-only
   ```
7. **Run tests**
   ```bash
   pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q
   ```

Full evidence pack: [docs/REVIEWER_EVIDENCE.md](./docs/REVIEWER_EVIDENCE.md)

---

## Retail Business Story

```
Visitor  →  Zone Visit  →  Billing Queue  →  Purchase
(CCTV)       (CCTV)          (CCTV)            (POS)
```

### How CCTV events become business metrics

1. Pipeline detects persons → assigns `external_track_id` → emits `vision.zone.entered` / `vision.zone.exited`.
2. Store entry (CAM 3 threshold) creates a **session** and flags `is_store_entry`.
3. Zone types map to funnel stages (`browse` → ZONE_VISIT, `billing_queue` → BILLING_QUEUE).
4. POS CSV creates **transactions**; linker matches billing-zone tracks to orders by time window.
5. Dashboard SQL aggregates distinct tracks, stage counts, zone visits, and revenue.

### Conversion rate

**Per-stage (sequential, first-touch):**

```
conversion_rate(S) = min(1.0, visitors_reaching_S_and_next / visitors_reaching_S)
drop_off_rate(S)   = 1 − conversion_rate(S)
```

Re-entering a stage increments `re_entry_count` but **not** stage `count`.

**Dashboard KPI (end-to-end):**

```
conversion_rate = min(1.0, PURCHASE.count / ENTRY.count)
```

### Re-entry handling

- Pipeline sets `is_reentry` on zone events after cooldown (`session.reentry_cooldown_minutes` in `pipeline/config.yaml`).
- Funnel calculator tracks re-touches separately from first-touch counts.
- Dashboard **Re-Entries** KPI uses `max(event reentry flags, sum of funnel re_entry_count)`.

### Edge cases (documented, not hidden)

| Case | Behavior |
|------|----------|
| Track without store entry | Counted in `unique_visitors`; may not create session or ENTRY funnel stage |
| Staff tracks | Filtered via `class_label=staff` and staff zones |
| POS order without CCTV match | Counted in POS KPIs, not in funnel PURCHASE |
| Batch/bootstrap ingest | Feed shows **stale** — correct for non-live data |
| Sparse frame logging | Pipeline emits `vision.frame.processed` every N sampled frames, not every frame |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dashboard empty / "Fetching…" | API down or wrong URL | Use `http://localhost:8000/dashboard/`; run `docker compose up -d` |
| HTTP 401 on APIs | Missing API key | Set `X-API-Key: purple-demo-key` |
| KPIs all zero | No vision events in DB | Check bootstrap: `CCTV_AUTO_BOOTSTRAP=true`; run `python scripts/bootstrap_cctv.py` |
| Funnel purchase = 1, POS = 24 | By design | Linkage matches billing tracks to POS; see POS_CCTV_LINKAGE.md |
| Feed: stale | Batch/bootstrap data | Expected; run live pipeline for fresh timestamps |
| `validate_submission` YOLO fails | No MP4s | `python scripts/setup_videos.py --source "..."` |
| Port 8000 busy | Stale uvicorn | Stop old process; use Docker Compose |
| Coverage fails locally | Below 96% gate | Match CI: `--cov-branch --import-mode=importlib` |

Diagnostic scripts:

```bash
python scripts/verify_dashboard_apis.py
python scripts/diagnose_dashboard.py
python scripts/audit_event_coverage.py
python scripts/generate_reality_audit_report.py
```

---

## Submission Notes

**Include in submission:**

- This repository with `README.md`, `DESIGN.md`, `CHOICES.md`
- [docs/REVIEWER_EVIDENCE.md](./docs/REVIEWER_EVIDENCE.md) — grader entry point
- [FINAL_REVIEW.md](./FINAL_REVIEW.md) · [FINAL_SCORE.md](./FINAL_SCORE.md) — rubric response (not duplicated elsewhere)

**Do not claim:**

- Live RTSP streaming (Phase 2)
- All POS orders are CCTV-linked (linkage is heuristic, demo shows partial match)
- Every sampled video frame is stored as an event (sparse `frame.processed` emission by design)

**Honest limitations:**

- CCTV MP4s are **not in git** (~680 MB); reviewers use committed bootstrap JSONL or run `setup_videos.py`
- Re-ID demo may use `mock_shared_visitor_embedding` for stable cross-camera proof — disclosed in [REID_EVIDENCE.md](./REID_EVIDENCE.md)
- Analytics are **on-read** from PostgreSQL; no Redis/Kafka in Phase 1

**Pre-submit checklist:**

```bash
python scripts/validate_submission.py --api-only
pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q
python scripts/verify_docker_compose.py
```

See [FINAL_SUBMISSION_CHECKLIST.md](./FINAL_SUBMISSION_CHECKLIST.md).

---

## Stack

- **API:** FastAPI, uvicorn, async SQLAlchemy, Alembic
- **DB:** PostgreSQL 16 (SQLite in unit tests)
- **CV:** OpenCV, Ultralytics YOLOv11, ByteTrack
- **Deploy:** Docker Compose (API + Postgres + optional pipeline worker)
- **CI:** GitHub Actions — pytest, coverage ≥96%, API validation, Docker verify

---

## Documentation index

| Document | Purpose |
|----------|---------|
| [DESIGN.md](./DESIGN.md) | Architecture, data flow, engines, AI-assisted decisions |
| [CHOICES.md](./CHOICES.md) | Model, schema, and API engineering decisions |
| [CI_EVIDENCE.md](./CI_EVIDENCE.md) | Last CI pytest/coverage/validation results |
| [docs/REVIEWER_EVIDENCE.md](./docs/REVIEWER_EVIDENCE.md) | Round 2 evidence pillars |
| [REALITY_AUDIT_REPORT.md](./REALITY_AUDIT_REPORT.md) | KPI lineage vs ingested events |
| [BUSINESS_STORY_REPORT.md](./BUSINESS_STORY_REPORT.md) | Retail journey and conversion math |

---

## License

Proprietary — adjust for your organization.
