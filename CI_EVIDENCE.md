# CI Evidence Report

**Generated:** 2026-05-30T18:43:34.181036+00:00  
**Workflow:** [.github/workflows/ci.yml](.github/workflows/ci.yml)  
**Python:** 3.11 · **Coverage gate:** ≥ 96%

## Executive summary

| Gate | Command / step | Result |
|------|----------------|--------|
| **Pytest** | `pytest tests/` | **270 passed** |
| **Coverage** | `--cov=app --cov-branch --cov-fail-under=96` | **96.5%** |
| **Validation** | `validate_submission.py --api-only` | **7/7 checks passed** |
| **Docker Compose** | `scripts/verify_docker_compose.py` | **PASS** |

---

## 1. GitHub Actions pipeline

Four jobs run on every push/PR to `main`, `master`, or `develop`:

| Job | Purpose |
|-----|---------|
| `pytest-and-coverage` | Migrations + full test suite with 96% branch coverage gate |
| `api-validation` | Uvicorn + `validate_submission.py --api-only` (7 checks) |
| `docker-compose-verify` | `docker compose up --build` + health + API validation |

A final `ci-evidence` job aggregates results into this report.

---

## 2. Pytest

```bash
python -m pytest tests/ \
  --cov=app --cov-branch --cov-fail-under=96 \
  --cov-report=xml:docs/evidence/coverage.xml \
  --junitxml=docs/evidence/junit.xml \
  --import-mode=importlib -q
```

| Metric | Value |
|--------|------:|
| Tests passed | **270** |
| Failures | 0 |
| Exit code | — |

---

## 3. Coverage

Scope: `app/` package (see `pyproject.toml`; `app/main.py` omitted).

| Metric | Value |
|--------|------:|
| Line coverage | **96.5%** |
| Lines covered | 2780 / 2836 |
| Gate | ≥ **96%** (branch-aware via `--cov-branch`) |

---

## 4. Validation (`--api-only`)

CI validates BI endpoints without YOLO pipeline ingest:

```bash
python scripts/seed_dev_data.py
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
python scripts/validate_submission.py --api-only
```

| Check | Endpoint |
|-------|----------|
| Liveness + DB | `GET /health` |
| Readiness | `GET /health/ready` |
| Metrics | `GET /api/v1/stores/{id}/metrics` |
| Funnel | `GET /api/v1/stores/{id}/funnel` |
| Heatmap | `GET /api/v1/stores/{id}/heatmap` |
| Anomalies | `GET /api/v1/stores/{id}/anomalies` |

**Result:** 7/7 checks passed


```
[PASS] GET /health
[PASS] GET /health/ready
[PASS] GET /metrics
[PASS] GET /funnel
[PASS] GET /heatmap
[PASS] GET /anomalies
[PASS] GET /health after checks

7/7 checks passed
```

---

## 5. Docker Compose verification

```bash
python scripts/verify_docker_compose.py
```

Steps:

1. `docker compose up --build -d postgres api`
2. Wait for API `/health/ready` (Postgres + migrations + seed)
3. Run `validate_submission.py --api-only` against `localhost:8000`
4. `docker compose down -v`

| Metric | Value |
|--------|-------|
| Status | **PASS** |
| API base | http://localhost:8000 |
| Validation | 7/7 checks passed |

---

## 6. Reproduce locally

```bash
pip install -e ".[dev]"
docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://si:si@localhost:5432/store_intelligence
python scripts/wait_for_database.py && alembic upgrade head
python scripts/generate_ci_evidence.py --run-local
python scripts/verify_docker_compose.py
```

See [CI_SETUP.md](./CI_SETUP.md) for troubleshooting.

---

## Artifacts

| File | Contents |
|------|----------|
| `docs/evidence/ci_pytest.json` | Pytest + coverage summary |
| `docs/evidence/ci_validation.json` | API validation output |
| `docs/evidence/ci_docker_compose.json` | Compose verification |
| `docs/evidence/coverage.xml` | Cobertura coverage (when generated) |
| `docs/evidence/junit.xml` | JUnit test report |

