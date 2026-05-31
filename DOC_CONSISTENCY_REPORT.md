# Documentation Consistency Report

**Generated:** 2026-05-30  
**Scope:** Full repository documentation audit — test counts, coverage figures, score files, cross-references

---

## Authoritative metrics

Verified by:

```bash
python -m pytest tests/ --collect-only -q          # 268 tests collected
python -m pytest tests/ --cov=app --cov-branch \
  --cov-fail-under=96 --import-mode=importlib -q   # 268 passed, 96.6% coverage
```

| Metric | Canonical value | Enforced in |
|--------|-----------------|-------------|
| Test count | **268** | `tests/` suite |
| Coverage (`app/`, branch-aware) | **96.6%** | `pyproject.toml` (`fail_under = 96`), CI |
| Full validation | **10/10** checks | `scripts/validate_submission.py` (real YOLO default) |
| CI validation | **7/7** checks | `scripts/validate_submission.py --api-only` |

Display convention: use **96.6%** in prose; pytest reports `96.60%` (equivalent).

---

## Score documentation (consolidated)

### Removed (outdated / conflicting)

| File | Reason |
|------|--------|
| `docs/FINAL_SCORE_98_CHECK.md` | Stale 229 tests / 96.37%; superseded |
| `docs/SCORE_IMPROVEMENT_REPORT.md` | Duplicate score narrative |
| `docs/98_SCORE_PLAN.md` | Milestone plan no longer authoritative |
| `docs/FINAL_SCORE_ESTIMATE.md` | Pre-fix 68/100 estimate contradicted current state |
| `docs/FINAL_REVIEW_RESPONSE.md` | Merged into root `FINAL_REVIEW.md` |
| `DOCUMENTATION_AUDIT.md` | Superseded by this report |

### Kept (authoritative)

| File | Purpose |
|------|---------|
| [FINAL_SCORE.md](./FINAL_SCORE.md) | Rubric score (**97/100**), verified metrics, reviewer quick-verify |
| [FINAL_REVIEW.md](./FINAL_REVIEW.md) | Point-by-point response to pre-submission review |

---

## Primary docs updated

| File | Changes |
|------|---------|
| `README.md` | 268 tests, 96.6%; links to `FINAL_SCORE.md` / `FINAL_REVIEW.md` |
| `CI_SETUP.md` | CI table: 268 passed, 96.6% |
| `DESIGN.md` | Link → `FINAL_REVIEW.md` |
| `CHOICES.md` | 268 tests, 96.6%; link → `FINAL_REVIEW.md` |
| `FINAL_SUBMISSION_CHECKLIST.md` | 268 tests, 96.6%; sign-off column |
| `FINAL_GAP_ANALYSIS.md` | Current metrics; score → `FINAL_SCORE.md` |
| `COVERAGE_GAP_REPORT.md` | Final column: 268 / 96.6% |
| `COVERAGE_IMPROVEMENT_PLAN.md` | Outcome: 268 / 96.6% |
| `coverage_gaps.txt` | 96.6%, 268 tests |
| `docs/REVIEWER_EVIDENCE.md` | 268 tests, 96.6% |
| `docs/SUBMISSION_CHECKLIST.md` | 268 tests, 96% gate |
| `docs/FINAL_SUBMISSION_PACKAGE.md` | Score 97/100; score doc links |
| `docs/FINAL_GAP_ANALYSIS.md` | 268 / 96.6%; score → `FINAL_SCORE.md` |
| `docs/INTERVIEW_PREPARATION.md` | Link → `FINAL_SCORE.md` |
| `docs/INTERVIEW_QA.md` | 268 tests, 96.6% |

---

## Intentionally unchanged (point-in-time evidence)

These files retain **run-specific** numbers (visitor counts, pipeline IDs, zone metrics). They are not global test/coverage claims:

- `REAL_PIPELINE_EVIDENCE.md`, `REID_EVIDENCE.md`, `DASHBOARD_HEALTH_REPORT.md`
- `docs/*_audit*.md`, `docs/*_validation*.md`, `docs/full_video_processing_report.md`
- `docs/evidence/*.json`

Historical baselines in coverage reports (e.g. **87.92%** initial, **145 tests**) remain labeled as **baseline** milestones, not current state.

---

## Cross-reference check

| Reference target | Status |
|------------------|--------|
| `FINAL_SCORE.md` | ✅ Present at repo root |
| `FINAL_REVIEW.md` | ✅ Present at repo root |
| Deleted score files | ✅ No remaining markdown links found |
| `validate_submission.py --mock` | Documented as opt-in only |
| Real YOLO default | `README.md`, `CI_SETUP.md`, `REAL_PIPELINE_EVIDENCE.md` |

---

## Residual items (non-blocking)

| Item | Notes |
|------|-------|
| README CI badge URL | May still use placeholder org/repo — see `FINAL_SCORE.md` (−1 pt) |
| CCTV MP4s not in git | Documented; `setup_videos.py` required on clean clone |
| `docs/FINAL_GAP_ANALYSIS.md` §2 | Some rows still describe pre-fix narrative for historical context; score section points to `FINAL_SCORE.md` |

---

## Verification commands

```bash
# Confirm no stale score filenames in tracked docs
rg "FINAL_SCORE_98|SCORE_IMPROVEMENT|98_SCORE_PLAN|FINAL_SCORE_ESTIMATE|FINAL_REVIEW_RESPONSE" --glob "*.md"

# Confirm canonical metrics in primary docs
rg "268 tests|96\.6%" README.md CI_SETUP.md FINAL_SCORE.md FINAL_REVIEW.md

# Re-run quality gate
python -m pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q
python scripts/validate_submission.py --api-only
```

---

## Summary

| Check | Result |
|-------|--------|
| Outdated score files removed | ✅ 6 files deleted |
| Authoritative score docs | ✅ `FINAL_SCORE.md` + `FINAL_REVIEW.md` only |
| Primary docs aligned on 268 / 96.6% | ✅ |
| Conflicting test/coverage numbers in primary docs | ✅ Cleared |
| Broken links to deleted score files | ✅ None found |
