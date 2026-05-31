# Reviewer Evidence Pack — Purple Tech Round 2

**Purpose:** Single entry point for graders — evidence, commands, expected results.  
**Store ID:** `00000000-0000-0000-0000-000000000101`  
**API key:** `purple-demo-key` (header `X-API-Key`)  
**Round 2 checklist:** [95_PLUS_CHECKLIST.md](../95_PLUS_CHECKLIST.md)

---

## Quick validation (5 minutes)

```bash
git clone <repo> && cd Smart-AI-StoreSurveillance
./scripts/setup_reviewer.sh          # Linux/macOS
# .\scripts\reviewer_setup.ps1       # Windows
```

| Check | Expected |
|-------|----------|
| Docker | `api` + `postgres` healthy |
| `validate_submission.py` | **10/10** (real YOLO default, with videos) |
| `validate_submission.py --api-only` | **7/7** (CI equivalent) |
| `pytest` | **270** pass, **≥96%** coverage (currently **96.6%**) |
| Dashboard | http://localhost:8000/dashboard/ |
| Evidence UI | http://localhost:8000/dashboard/evidence.html |

---

## Round 2 evidence pillars

| Priority | Document | What it proves |
|----------|----------|----------------|
| **1. Re-ID** | [REID_EVIDENCE.md](../REID_EVIDENCE.md) | Same visitor UUID on 4 cameras; screenshots + event trail |
| **2. Real YOLO** | [REAL_PIPELINE_EVIDENCE.md](../REAL_PIPELINE_EVIDENCE.md) | YOLOv11 on Brigade Road MP4s; default validation path |
| **3. Doc consistency** | [DOC_CONSISTENCY_REPORT.md](../DOC_CONSISTENCY_REPORT.md) | Single test/coverage numbers; score docs consolidated |
| **4. Business funnel** | [BUSINESS_STORY_REPORT.md](../BUSINESS_STORY_REPORT.md) | Visitor → Zone → Billing → Purchase + conversion math |
| **5. CI / Docker** | [CI_EVIDENCE.md](../CI_EVIDENCE.md) | Pytest, coverage gate, API validation, Compose verify |

**Score docs:** [FINAL_SCORE.md](../FINAL_SCORE.md) · [FINAL_REVIEW.md](../FINAL_REVIEW.md)

---

## API endpoints (evidence)

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics?metric=visitor.count"

curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel"

curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies"
```

Health probes (`/health`, `/health/ready`) are unauthenticated.

---

## Regenerate evidence (optional)

Requires CCTV under `data/videos/` and Docker for CI/Docker steps.

```bash
python scripts/generate_reid_evidence.py
python scripts/generate_real_pipeline_evidence.py --max-frames 20
python scripts/generate_business_story_report.py
python scripts/verify_docker_compose.py
python scripts/generate_ci_evidence.py
python scripts/generate_95_plus_checklist.py
```

---

## Real YOLO validation

Default (no `--mock`):

```bash
python scripts/validate_submission.py
python scripts/generate_real_pipeline_evidence.py --max-frames 20
```

Mock is **opt-in only:** `python scripts/validate_submission.py --mock`

---

## CI pipeline

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

| Job | Proves |
|-----|--------|
| `pytest-and-coverage` | **270 tests**, **≥96%** branch coverage |
| `api-validation` | **7/7** BI checks |
| `docker-compose-verify` | Full stack build + health + validation |
| `ci-evidence` | Publishes [CI_EVIDENCE.md](../CI_EVIDENCE.md) |

Local reproduction: [CI_SETUP.md](../CI_SETUP.md)

---

## Business funnel (dashboard)

Open http://localhost:8000/dashboard/ → **Business story**

```
Visitor → Zone Visit → Billing Queue → Purchase
```

Sequential conversion: visitors reaching stage **and** next stage ÷ visitors at stage (capped 100%).

---

## Known operational step

CCTV MP4s (~680 MB) are **not in git**:

```bash
python scripts/setup_videos.py --source "/path/to/CCTV Footage"
```

Without videos: tests, API, CI, and Docker validation still pass; full YOLO 10/10 requires local videos.

---

## Test suite

```
270 tests | 96.6% branch coverage on app/
fail_under = 96 in pyproject.toml
```
