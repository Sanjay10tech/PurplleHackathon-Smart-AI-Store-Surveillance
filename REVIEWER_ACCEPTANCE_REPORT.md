# Reviewer Acceptance Report — Purple Tech Round 2

**Generated:** 2026-05-31T11:18:27+00:00  
**Reviewer mode:** Round 2 — reviewer-visible behavior only  
**API base probed:** `http://localhost:8000`  
**Demo store:** `00000000-0000-0000-0000-000000000101`  
**API key:** `purple-demo-key` (`X-API-Key`)

All figures below come from **commands run in this evaluation session**. Stale reports in `docs/` are cited only as on-disk artifacts, not as live passes.

---

## Executive summary

| Metric | Value |
|--------|------:|
| **Final score** | **30 / 100** |
| **Acceptance gate** | **FAIL** (2 / 6 pass) |
| **Top-30 readiness** | **9 / 30 pass** |
| **Live API availability** | **0 / 8 endpoints responded** |

**Verdict:** Submission artifacts and test suite are strong, but **reviewer-visible runtime is not demonstrable in this session** because Docker Desktop and `localhost:8000` are unavailable. A Round 2 reviewer cannot verify funnel, heatmap, POS KPIs, or dashboard without a running stack.

---

## 1. Live API probe (this session)

**Command:** Python `urllib` probe, 10 s timeout per endpoint  
**Result:** every call returned `timed out`

| Endpoint | HTTP | Reviewer-visible data |
|----------|------|------------------------|
| `GET /health` | **timeout** | not retrieved |
| `GET /reviewer` | **timeout** | not retrieved |
| `GET /api/v1/stores/{id}/metrics?metric=visitor.count` | **timeout** | not retrieved |
| `GET /api/v1/stores/{id}/funnel` | **timeout** | not retrieved |
| `GET /api/v1/stores/{id}/heatmap` | **timeout** | not retrieved |
| `GET /api/v1/stores/{id}/anomalies` | **timeout** | not retrieved |
| `GET /api/v1/stores/{id}/dashboard/summary` | **timeout** | not retrieved |
| `GET /dashboard/` | **000** (connection failed, 8 s) | UI not loaded |

**Supplementary curl:** `curl --connect-timeout 8 http://127.0.0.1:8000/health` → `health_http=000`

---

## 2. Reviewer-visible metrics (required checklist)

| Metric | Status | Evidence this session |
|--------|--------|------------------------|
| 5 CCTV videos processed | **NOT VERIFIED LIVE** | API `/reviewer` and `/dashboard/summary` timed out |
| Total frames analyzed | **NOT VERIFIED LIVE** | API timed out |
| Total events generated | **NOT VERIFIED LIVE** | API timed out |
| Entry count | **NOT VERIFIED LIVE** | API timed out |
| Exit count | **NOT VERIFIED LIVE** | API timed out |
| Re-entry count | **NOT VERIFIED LIVE** | API timed out |
| Funnel counts | **NOT VERIFIED LIVE** | `GET /funnel` timed out |
| Heatmap counts | **NOT VERIFIED LIVE** | `GET /heatmap` timed out |
| POS purchases | **NOT VERIFIED LIVE** | `GET /dashboard/summary` timed out |
| Revenue from CSV | **NOT VERIFIED LIVE** | API timed out (CSV dry-run below is offline only) |
| Metrics API | **FAIL** | timed out |
| Funnel API | **FAIL** | timed out |
| Anomalies API | **FAIL** | timed out |
| Dashboard | **FAIL** | HTTP 000 |

### Offline artifacts (not substitute for live reviewer proof)

| Artifact | Value | Command / source |
|----------|-------|------------------|
| MP4 files on disk | **5 / 5** | `CAM 1.mp4` … `CAM 5.mp4` present under `data/videos/` |
| Bootstrap JSONL events | **37** | `data/reviewer/yolo_bootstrap_events.jsonl` |
| Bootstrap cameras | **5** | UUIDs `…0201`–`…0205` |
| Bootstrap event types | 10× `vision.frame.processed`, 11× `vision.zone.entered`, 5× `vision.zone.exited`, 11× `vision.track.ended` | JSONL parse this session |
| Bootstrap detector | **yolo only** (37 / 37) | JSONL parse this session |
| POS CSV dry-run orders | **24** | `python scripts/ingest_pos_csv.py --dry-run` |
| POS CSV dry-run revenue (NMV) | **₹34,831.74** | same dry-run |
| Offline YOLO run report (on disk) | 5 videos, 250 frames, 44 events emitted | `docs/full_video_processing_report.md` (generated 2026-05-31T09:59:36Z — **not re-run this session**) |
| Pipeline generates events (code path) | **3 events / 5 frames / 1 video** | `python -m pipeline.run --mock --camera "CAM 1" --max-frames 5` this session |

---

## 3. Docker compose verification

| Check | Result | Evidence |
|-------|--------|----------|
| `docker ps` | **FAIL** | command hung ~161 s, no container list |
| `docker compose up --build -d` | **FAIL** (prior attempt this environment) | Docker Desktop Linux engine HTTP 500 on image pull |
| Cold-start acceptance | **NOT VERIFIED** | stack never reached healthy state this session |

---

## 4. Tests (non-UI, reviewer confidence)

```
279 passed, 4 warnings in 23.08s
```

**Command:** `python -m pytest -q --tb=no`  
**Exit code:** `0`

---

## 5. Acceptance gate status

| # | Gate | Status | Evidence |
|---|------|--------|----------|
| 1 | `docker compose up` succeeds from clean clone | **FAIL** | Docker daemon unavailable / HTTP 500 |
| 2 | `/health` returns 200 | **FAIL** | timed out (10 s) |
| 3 | `/api/v1/stores/{demo_store_id}/metrics` returns valid data | **FAIL** | timed out |
| 4 | `DESIGN.md` exists | **PASS** | file present at repo root |
| 5 | `CHOICES.md` exists | **PASS** | file present at repo root |
| 6 | Detection pipeline generates events | **PASS** (offline) | mock pipeline run → 3 events; bootstrap JSONL 37 events; not verified through live API ingest |

**Acceptance gate:** **FAIL** (2 / 6)

---

## 6. Top-30 readiness (Round 2)

| # | Criterion | Pass | Evidence |
|---|-----------|:----:|----------|
| 1 | `DESIGN.md` present | ✓ | repo root file |
| 2 | `CHOICES.md` present | ✓ | repo root file |
| 3 | Dashboard static assets present | ✓ | `dashboard/index.html` |
| 4 | Five CCTV MP4s on disk | ✓ | 5 files in `data/videos/` |
| 5 | Bootstrap JSONL ≥ 10 events | ✓ | 37 lines |
| 6 | Bootstrap spans 5 cameras | ✓ | 5 camera UUIDs in JSONL |
| 7 | Bootstrap uses real YOLO mode only | ✓ | `detector_mode=yolo` × 37 |
| 8 | pytest suite green | ✓ | 279 passed |
| 9 | POS CSV parses orders + revenue | ✓ | 24 orders, ₹34,831.74 NMV dry-run |
| 10 | Offline YOLO processing report on disk | ✓ | `docs/full_video_processing_report.md` (5/5 videos) |
| 11 | Pipeline code emits events | ✓ | mock run → 3 events this session |
| 12 | `docker compose up` succeeds | ✗ | Docker engine failure / hang |
| 13 | `GET /health` HTTP 200 | ✗ | timed out |
| 14 | `GET /reviewer` HTTP 200 | ✗ | timed out |
| 15 | `ready_for_review` true | ✗ | API unavailable |
| 16 | 5 CCTV videos processed (live API) | ✗ | not retrieved |
| 17 | Total frames analyzed (live API) | ✗ | not retrieved |
| 18 | Total events generated (live API) | ✗ | not retrieved |
| 19 | Entry count (live API) | ✗ | not retrieved |
| 20 | Exit count (live API) | ✗ | not retrieved |
| 21 | Re-entry count (live API) | ✗ | not retrieved |
| 22 | Funnel counts (live API) | ✗ | timed out |
| 23 | Heatmap counts (live API) | ✗ | timed out |
| 24 | POS purchases (live dashboard API) | ✗ | timed out |
| 25 | Revenue (live dashboard API) | ✗ | timed out |
| 26 | Metrics API HTTP 200 + body | ✗ | timed out |
| 27 | Funnel API HTTP 200 + body | ✗ | timed out |
| 28 | Anomalies API HTTP 200 + body | ✗ | timed out |
| 29 | Dashboard summary API HTTP 200 | ✗ | timed out |
| 30 | Dashboard UI loads in browser | ✗ | curl HTTP 000 |

**Top-30 readiness:** **9 / 30 (30%)**

---

## 7. Remaining blockers

1. **Docker Desktop Linux engine down** — `docker ps` hangs; `docker compose up` returns HTTP 500 on image inspect. Blocks cold-start demo.
2. **API not listening on port 8000** — all reviewer endpoints time out or refuse connection; dashboard UI unreachable.
3. **Live reviewer proof unavailable** — cannot confirm `/reviewer` 8-check checklist, funnel stages, heatmap zones, or POS↔CCTV linkage in UI/API.
4. **Archived API verification not re-run** — `docs/REVIEWER_API_VERIFICATION.md` (2026-05-31T08:50Z, 10/10 HTTP 200) exists on disk but was **not reproduced** this session; excluded from score.
5. **Reviewer must restart stack locally** before Round 2 sign-off:

```powershell
.\scripts\restart_reviewer_stack.ps1
python scripts/verify_reviewer_api_links.py
python scripts/generate_reviewer_acceptance_report.py
```

---

## 8. Commands used (this evaluation)

```powershell
python -m pytest -q --tb=no
python -c "<urllib probe of /health, /reviewer, metrics, funnel, heatmap, anomalies, dashboard/summary>"
curl.exe --connect-timeout 8 --max-time 10 http://127.0.0.1:8000/health
curl.exe --connect-timeout 8 --max-time 10 http://127.0.0.1:8000/dashboard/
docker ps --format "table {{.Names}}\t{{.Status}}"
python scripts/ingest_pos_csv.py --dry-run
python -c "<bootstrap JSONL + video inventory parse>"
python -m pipeline.run --mock --camera "CAM 1" --max-frames 5
```

---

## 9. Reviewer quick-start (when Docker is healthy)

```bash
docker compose up --build -d
curl http://localhost:8000/reviewer
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel"
open http://localhost:8000/dashboard/
```
