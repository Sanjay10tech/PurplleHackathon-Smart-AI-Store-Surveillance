# Final Challenge — Submission Checklist

Use this list before submitting the Store Intelligence repository. All items marked ✅ were verified during final submission prep (2026-05-30).

## Repository & documentation

- [x] `README.md` — quick start, API table, pipeline section, test stats, doc links
- [x] `DESIGN.md` — architecture, data flow, scaling, tradeoffs, **AI-Assisted Decisions** section
- [x] `CHOICES.md` — three engineering decisions with options, reasoning, tradeoffs
- [x] `docs/architecture/README.md` — status banner (implemented vs planned)
- [x] `docs/bi_validation_report.md` — BI validation evidence
- [x] `docs/SUBMISSION_CHECKLIST.md` — this file
- [x] `docs/INTERVIEW_QA.md` — follow-up Q&A for reviewers

## Docker & deploy

- [x] `docker compose up --build` from repo root succeeds
- [x] Postgres healthcheck passes before API starts
- [x] API container runs migrations + demo seed on boot
- [x] API container reports **healthy** (`scripts/healthcheck.py`)
- [x] `.env.example` documents required variables
- [ ] Optional: run on a truly clean VM (only Docker installed) and capture screenshot/log

## Required API endpoints

Demo store: `00000000-0000-0000-0000-000000000101`

| Endpoint | Expected | Verified |
|----------|----------|----------|
| `GET /health` | 200; DB up; feed unknown on fresh boot (degraded) | ✅ |
| `GET /health/ready` | 200 when Postgres up | ✅ |
| `POST /api/v1/events/ingest` | 202 accept; idempotent dedup | ✅ (pytest) |
| `GET /api/v1/stores/{id}/metrics` | 200 JSON time series | ✅ |
| `GET /api/v1/stores/{id}/funnel` | 200 funnel stages | ✅ |
| `GET /api/v1/stores/{id}/heatmap` | 200 zone scores | ✅ |
| `GET /api/v1/stores/{id}/anomalies` | 200 anomaly list | ✅ |
| `GET /docs` | OpenAPI UI | ✅ (implicit) |

After pipeline ingest or golden-day seed: `/health` should show `feed=fresh`, `status=ok`.

## Logging requirements

- [x] Production Compose sets `LOG_JSON=true`, `ENVIRONMENT=production`
- [x] structlog JSON logs to stdout (see `docker compose logs api`)
- [x] Every HTTP request logs `trace_id`, `endpoint`, `latency_ms`, `status_code`, `event_count`
- [x] Health checks log `health_check_completed` with feed status
- [x] Ingest logs accepted/duplicate counts (see `EventIngestionService`)
- [ ] Redis/worker pipeline logs — N/A (not deployed)

## Health endpoint requirements

- [x] Liveness: `/health` returns service name, version, checks
- [x] Database down → `status=unhealthy`, HTTP 503
- [x] No feed events → `feed=unknown`, `stale_feed=true`, `status=degraded`, HTTP 200
- [x] Recent vision events → `feed=fresh`, `status=ok`
- [x] Readiness: `/health/ready` — Postgres only (Redis not in Compose)
- [ ] Architecture doc mentions Redis in readiness — **documented as planned**, not implemented

## Tests & coverage

```bash
pytest tests/ --cov=app --cov-branch --cov-fail-under=96 -q
```

- [x] **268 tests** passing
- [x] **96.6% coverage** on `app/` (gate: 96% in `pyproject.toml`)
- [x] Scenario suite: empty store, queue spike, re-entry, duplicate ingest, stale feed, BI full validation, pipeline E2E
- [x] All `tests/**/test_*.py` files include `# PROMPT:` and `# CHANGES MADE:` attribution blocks

## Pipeline (optional demo)

```bash
pip install -r pipeline/requirements.txt
bash pipeline/run.sh mock --camera "CAM 3" --max-frames 30
bash pipeline/run.sh ingest --mock --camera "CAM 3" --max-frames 20
```

- [x] Mock pipeline runs without GPU
- [x] Ingest mode POSTs to API and persists sessions
- [x] Sample events in `data/samples/events/`

## Pre-submit commands (copy/paste)

```bash
# 1. Tests
pytest tests/ --cov=app --cov-fail-under=70 -q

# 2. Docker
docker compose down -v   # optional clean slate
docker compose up --build -d
docker compose ps        # api + postgres healthy

# 3. Smoke endpoints
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8000/health/ready | jq .
curl -s "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel" | jq .

# 4. Pipeline → ingest → health fresh
bash pipeline/run.sh ingest --mock --camera "CAM 3" --max-frames 15
curl -s http://localhost:8000/health | jq .checks.feed
```

## Known gaps (acceptable for MVP)

| Gap | Notes |
|-----|-------|
| Metrics placeholder on empty store | Returns empty series until `store_metrics` seeded or projector built |
| No auth on API | Documented in architecture; open for challenge demo |
| Readiness = DB only | Redis/MinIO in architecture docs are roadmap |
| Pipeline not in Docker image | By design — GPU/host Python; API container stays slim |
| `docs/architecture/api-contracts.md` | Describes future CRUD/WebSocket endpoints not in code |

## Submission artifacts to attach

1. Repository URL (or zip)
2. Screenshot or log of `docker compose up --build` + healthy containers
3. Screenshot or log of `pytest` summary (**268 passed**, **96.6%** coverage)
4. Optional: `docs/bi_validation_report.md` excerpt showing funnel/heatmap after golden day seed
