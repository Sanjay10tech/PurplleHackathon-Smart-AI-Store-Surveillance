# Final Pre-Submission Audit — Purple Tech Challenge

**Evaluator role:** Official Purple Tech Challenge evaluator (strict)  
**Audit date:** 2026-05-31  
**Repository:** Smart-AI-StoreSurveillance  
**Scope:** Verification only — no feature additions, no architecture redesign

---

## Acceptance Gate

| Gate | Result | Evidence |
|------|--------|----------|
| `docker compose up` | **PASS** | `api` + `postgres` healthy; port 8000 live |
| API availability | **PASS** | `GET /health` 200, `GET /health/ready` 200, `/docs` serves OpenAPI |
| Event generation | **CONDITIONAL PASS** | Events exist after pipeline ingest or persisted DB volume; **not** produced by `docker compose up` alone on empty DB |
| `DESIGN.md` | **PASS** | Present, describes hexagonal layout, implemented vs future components |
| `CHOICES.md` | **PASS** | Three documented decisions (detector, schema, analytics compute model) |
| Stability | **FAIL** | **6 pytest failures** in current workspace (271 passed); CI artifact from 2026-05-30 showed 270/270 green — **regression since last green CI** |

**Gate verdict: FAIL** (stability blocker; event generation not self-contained in compose)

---

## Category Scores (strict)

### 1. Detection Pipeline — **19 / 30**

| | |
|---|---|
| **Evidence** | 5 MP4s present locally; `validate_submission.py` runs real YOLO on CAM 3/1/5 (25 frames each) → 10/10 checks; DB shows 42 YOLO + 66 mock vision events; entries=3, exits=1; `/reviewer` 8/8 when DB seeded |
| **Risk** | **HIGH** |
| **Reviewer concerns** | Mixed mock+YOLO in same store metrics without hard separation; default validation ingests **3 of 5** cameras; fresh clone has **zero** CCTV events until manual pipeline; POS (24 orders) poorly linked to CCTV journeys (funnel PURCHASE=3); `detector_mode: mixed` undermines “real CV pipeline” claim |

---

### 2. API & Business Logic — **27 / 35**

| | |
|---|---|
| **Evidence** | Funnel 4-stage with conversion/drop-off/re-entry; heatmap 8 layout zones; POS CSV auto-ingest (₹34,831.74, 24 orders); dashboard summary + `/reviewer` checklist; retail journeys + Re-ID evidence endpoints; idempotent ingest; API key on protected routes |
| **Risk** | **MEDIUM** |
| **Reviewer concerns** | Purchase count ambiguity (24 POS vs 3 funnel) even with footnotes; conversion 100% looks inflated; unique visitors (9) vs entries (3) vs sessions (2) needs explanation under pressure; `/health` status `degraded` while `ready_for_review: true` |

---

### 3. Production Readiness — **12 / 20**

| | |
|---|---|
| **Evidence** | Docker Compose API+Postgres; Alembic on boot; seed + POS ingest; health/ready probes; structured logging; GitHub Actions CI (pytest 96% gate, API validation, compose verify); `validate_submission.py` 10/10 with videos+YOLO |
| **Risk** | **HIGH** |
| **Reviewer concerns** | **6 failing tests** break CI if pushed as-is; CCTV videos **not in repo** (~680 MB gitignored) — reviewer must run `setup_videos.py`; pipeline not in default compose profile; STALE_FEED CRITICAL on first open if no recent ingest; Python 3.13 local vs CI 3.11 drift |

**Failing tests (current workspace):**
- `tests/test_analytics_service.py` (2) — placeholder message mismatch after period/reviewer changes
- `tests/test_ws_dashboard.py` — dashboard title string changed
- `tests/test_ci_coverage.py` — dashboard schema missing `reviewer_headline`
- `tests/scenarios/test_pipeline_e2e.py` — e2e pipeline chain
- `tests/scenarios/test_bi_full_validation.py` — full BI chain

---

### 4. Engineering Thinking — **13 / 15**

| | |
|---|---|
| **Evidence** | `DESIGN.md` with honest implemented vs Phase 2 table; `CHOICES.md` with options/tradeoffs; ADRs in `docs/architecture/`; evidence pack in `docs/evidence/`; mock mode explicitly documented |
| **Risk** | **LOW** |
| **Reviewer concerns** | DESIGN.md still lists some “future” items that are implemented (minor doc drift); CHOICES.md says “no labeled footage yet” while submission uses real Brigade CCTV — wording aged |

---

## Estimated Total Score

| Category | Max | Score |
|----------|-----|------:|
| Detection Pipeline | 30 | 19 |
| API & Business Logic | 35 | 27 |
| Production Readiness | 20 | 12 |
| Engineering Thinking | 15 | 13 |
| **Total** | **100** | **71** |

---

## Remaining Risks (submission blockers)

1. **Pytest regression (6 failures)** — CI will fail; must restore green before submit  
2. **CCTV not auto-generated on `docker compose up`** — reviewer sees empty funnel on fresh `-v` unless README steps followed  
3. **Mock + YOLO mixed in production DB** — undermines detection credibility  
4. **Videos external to repo** — clone-only evaluation fails without manual video setup  
5. **POS↔CCTV linkage weak** — 24 POS orders vs 3 funnel purchases  
6. **Last green CI (2026-05-30) ≠ current HEAD** — evidence stale after reviewer-visibility edits  

---

## Evaluator Notes (what worked in 10-minute review)

- `/reviewer` public endpoint — strong first impression when DB seeded  
- Dashboard hero row + footnotes — clarifies POS vs funnel purchases  
- `validate_submission.py` 10/10 — best single proof command  
- Brigade POS CSV integration — clearly real data  
- Funnel re-entry counts visible in API and dashboard  

---

## Final Verdict (strict)

See summary block below.
