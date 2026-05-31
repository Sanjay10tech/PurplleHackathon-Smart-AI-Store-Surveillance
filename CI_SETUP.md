# CI Setup — Store Intelligence

**Workflow:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml)  
**Coverage gate:** `app/` ≥ **96%** (line + branch via `--cov-branch`)  
**Python:** 3.11

### Local verification (2026-05-30)

| Step | Result |
|------|--------|
| `pytest tests/ --cov=app --cov-branch --cov-fail-under=96` | **270 passed**, **96.6%** coverage |
| `python scripts/validate_submission.py --api-only` | **7/7 checks passed** |

---

## What CI runs

Four jobs on every push/PR:

| Job | Steps | Purpose |
|-----|-------|---------|
| **pytest-and-coverage** | migrate → pytest + XML/JUnit reports | **270 tests**, **≥96%** branch coverage gate |
| **api-validation** | seed → uvicorn → `validate_submission.py --api-only` | **7/7** BI endpoint checks |
| **docker-compose-verify** | `scripts/verify_docker_compose.py` | Full stack build + health + validation |
| **ci-evidence** | `scripts/generate_ci_evidence.py` | Writes [`CI_EVIDENCE.md`](CI_EVIDENCE.md) artifact |

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `pip install -e ".[dev]"` | Install API + test dependencies |
| 2 | `python scripts/wait_for_database.py` | Wait for PostgreSQL service |
| 3 | `alembic upgrade head` | Apply database migrations |
| 4 | `pytest tests/ --cov=app --cov-branch --cov-fail-under=96` | Unit/integration tests + coverage gate |
| 5 | `python scripts/seed_dev_data.py` | Seed demo store for API validation |
| 6 | `uvicorn app.main:app` (background) | Start API on port 8000 |
| 7 | `python scripts/validate_submission.py --api-only` | CI: health + BI endpoints (no YOLO ingest) |
| 8 | `python scripts/verify_docker_compose.py` | Docker Compose build + health + validation |
| 9 | `python scripts/generate_ci_evidence.py` | Aggregate results → `CI_EVIDENCE.md` |

Full local validation runs **real YOLO** on CCTV by default. Use `--mock` only for fast dev shortcuts:

```bash
python scripts/validate_submission.py              # real YOLO ingest (default)
python scripts/validate_submission.py --mock         # optional mock trajectories
python scripts/validate_submission.py --api-only     # CI: API checks only
```

---

## Local reproduction

### Prerequisites

- Python 3.11+
- PostgreSQL 16 (or Docker Compose)

### Option A — Docker PostgreSQL

```bash
docker compose up -d postgres

export DATABASE_URL=postgresql+asyncpg://si:si@localhost:5432/store_intelligence
export API_KEY=purple-demo-key
export API_KEY_REQUIRED=true

pip install -e ".[dev]"
python scripts/wait_for_database.py
alembic upgrade head

# Tests + coverage (must pass >=96%)
python -m pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q

# Validation (API must be running)
python scripts/seed_dev_data.py
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
python scripts/validate_submission.py --api-only
```

### Option B — SQLite (tests only)

Tests use in-memory SQLite via `tests/conftest.py` — no PostgreSQL required for pytest:

```bash
pip install -e ".[dev]"
python -m pytest tests/ --cov=app --cov-branch --cov-fail-under=96 -q
```

API validation requires PostgreSQL (health check uses real DB).

---

## Validation script

[`scripts/validate_submission.py`](scripts/validate_submission.py) runs **real YOLO ingest by default** when CCTV videos are present (10 checks). CI uses `--api-only` (7 checks, no pipeline). Mock trajectories are opt-in via `--mock`.

[`scripts/generate_real_pipeline_evidence.py`](scripts/generate_real_pipeline_evidence.py) reproduces the full proof bundle and writes [`REAL_PIPELINE_EVIDENCE.md`](REAL_PIPELINE_EVIDENCE.md).

### CI mode (`--api-only`)

| Check | Endpoint |
|-------|----------|
| Liveness + DB | `GET /health` |
| Readiness | `GET /health/ready` |
| Metrics | `GET /api/v1/stores/{id}/metrics` |
| Funnel | `GET /api/v1/stores/{id}/funnel` |
| Heatmap | `GET /api/v1/stores/{id}/heatmap` |
| Anomalies | `GET /api/v1/stores/{id}/anomalies` |

Set `API_KEY` (default `purple-demo-key`) when `API_KEY_REQUIRED=true`.

---

## Coverage configuration

From [`pyproject.toml`](pyproject.toml):

```toml
[tool.coverage.run]
source = ["app"]
omit = ["app/main.py"]

[tool.coverage.report]
fail_under = 96
```

CI enforces the same threshold with `--cov-fail-under=96 --cov-branch`.

---

## Troubleshooting

| Failure | Fix |
|---------|-----|
| Coverage below 96% | Run `python -m pytest tests/ --cov=app --cov-branch --cov-report=term-missing` locally |
| `validate_submission` connection refused | Ensure uvicorn is running on port 8000 |
| PostgreSQL not ready | Increase health retries or run `docker compose ps` |
| Migrations fail | `alembic upgrade head` against clean DB |

---

## Related scripts

| Script | Role |
|--------|------|
| `scripts/verify_docker_compose.py` | CI Docker Compose verification |
| `scripts/generate_ci_evidence.py` | Generate [`CI_EVIDENCE.md`](CI_EVIDENCE.md) |
| `scripts/verify_dashboard_apis.py` | Dashboard endpoint smoke test (local dev) |
| `scripts/generate_reid_validation.py` | Re-ID audit report (not in CI) |
| `scripts/generate_retail_journey_validation.py` | Retail journey proof (not in CI) |
