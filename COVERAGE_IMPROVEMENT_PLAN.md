# Coverage Improvement Plan

**Goal:** Raise `app/` coverage from **87.92% → ≥96%** while preserving test quality.  
**Outcome:** **96.6%** (**268 tests**, all passing) as of 2026-05-30.

---

## Phase 1 — Baseline Analysis ✅

- Ran full suite with branch coverage enabled.
- Identified 14 modules below 90% coverage; top offenders were repositories (`event`, `store_metric`, `transaction`) and routers (`events`, `health`).
- Documented that `pipeline/` is excluded from the default coverage gate.

---

## Phase 2 — High-ROI Test Additions ✅

### New test modules

| File | Focus |
|------|-------|
| `tests/unit/test_app_infrastructure.py` | Settings, logging, DB singleton/rollback, exceptions, observability context |
| `tests/unit/test_repository_coverage.py` | Analytics/domain_event repos, CRUD, list filters, idempotency |
| `tests/unit/test_service_branches.py` | Funnel staff/orphan signals, heatmap dwell/confidence, anomaly merge |
| `tests/unit/test_ingestion_router_branches.py` | Invalid JSON, persistence errors, batch-too-large, schema validation |
| `tests/unit/test_coverage_completion.py` | IntegrityError recovery, validation cache, readiness 503, PG upsert mock |
| `tests/unit/test_coverage_final.py` | Repository races, router 207/503, cross-boundary funnel, anomaly detector edges |

### Extended existing modules

| File | Additions |
|------|-----------|
| `tests/unit/test_anomaly_detector.py` | WARN queue spike, CRITICAL conversion drop, stale feed WARN |
| `tests/test_pipeline.py` | Fixed `test_yolo_bbox_filters` area assertion |

---

## Phase 3 — Branch-First Priorities (Completed)

Tests were written to hit **decision arms**, not just lines:

1. **Idempotency races** — `IntegrityError` during nested transaction, then recover via `get_by_id` or `get_by_idempotency_key`.
2. **HTTP semantics** — 202 / 207 / 422 / 503 status codes from real router calls.
3. **Empty / invalid payloads** — non-object JSON, invalid event types, tenant mismatch, duplicate keys in batch.
4. **Funnel edge cases** — staff exclusion, orphan session IDs, cross-period session fetch, purchase without session.
5. **Anomaly / heatmap** — queue zone filtering, dead-zone peak=0 skip, staff zone skip, exit without dwell.
6. **Health / readiness** — DB down, stale feed, scoped feed timestamp queries.

---

## Phase 4 — Quality Guardrails ✅

- No duplicate assertions of already-covered happy paths.
- Integration tests retained for end-to-end BI chain; unit tests added for isolated branches.
- SQLite used for speed; PostgreSQL-specific paths mocked where dialect differs (e.g. `pg_insert` upsert).
- `fail_under` raised from **70 → 96** in `pyproject.toml`.

---

## Phase 5 — Optional Follow-Up (Not Required for 96%)

If targeting **98%+**, address Tier 1 items from `COVERAGE_GAP_REPORT.md`:

| Priority | Action | Est. gain |
|----------|--------|-----------|
| P1 | `store_metric_repository`: force `IntegrityError` on SQLite create with concurrent bucket | ~1.5% |
| P1 | `transaction_repository`: `list_by_store` with `from_ts`/`to_ts`; IntegrityError re-raise without ref | ~1.0% |
| P2 | `event_repository`: IntegrityError → idempotency-key recovery (lines 37–39) | ~0.5% |
| P2 | `funnel_service`: session missing from index after `get_sessions_by_ids` returns empty | ~0.5% |
| P3 | Partial branch arms in observability / analytics repos | ~0.3% |

**Pipeline coverage** (separate initiative): add `tests/` targeting `pipeline/tracker.py`, `pipeline/detector.py`, re-entry and queue-abandonment logic with `--cov=pipeline`.

---

## Verification Checklist

- [x] All tests pass: `268/268`
- [x] Branch coverage enabled
- [x] Total ≥ 96% (**96.6%**)
- [x] `COVERAGE_GAP_REPORT.md` generated
- [x] `COVERAGE_IMPROVEMENT_PLAN.md` generated
- [x] HTML report in `htmlcov/`
- [x] CI gate `fail_under = 96`

---

## Commands

```powershell
# Full suite + terminal report
python -m pytest tests/ --cov=app --cov-branch --cov-report=term-missing --import-mode=importlib -q

# HTML dashboard
python -m pytest tests/ --cov=app --cov-branch --cov-report=html:htmlcov --import-mode=importlib -q

# Single module during development
python -m pytest tests/unit/test_coverage_final.py -v --import-mode=importlib
```

---

## Metrics Timeline

| Milestone | Tests | Coverage |
|-----------|-------|----------|
| Initial baseline | 145 | 87.92% |
| After first unit batch | ~195 | ~93.85% |
| After final gap closure | **268** | **96.6%** |
