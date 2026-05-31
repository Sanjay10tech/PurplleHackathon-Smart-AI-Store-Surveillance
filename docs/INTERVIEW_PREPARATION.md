# Interview Preparation — Purple Challenge (Strict Reviewer Lens)

Use this document to prepare for oral defense. Questions below are **what a skeptical Purple grader is likely to ask** after reading this repository. Answers marked **Strong** pass scrutiny; **Weak** answers will cost marks.

---

## How to open the defense (30 seconds)

**Strong opener:**

> “We delivered a Dockerized Intelligence API with on-read funnel, heatmap, and anomaly engines, plus an offline pipeline that reads Purplle MP4s from `data/videos/` and POSTs `vision.*` events. Mock trajectory mode makes the demo reproducible without GPU; YOLOv11 code path exists for real detection. Event bus, WebSocket dashboard, and auth are documented as Phase 2, not hidden.”

**Weak opener (avoid):**

> “We built a complete real-time event-driven Store Intelligence platform with YOLO on all cameras.”

That sentence is **false** against the code and will end the interview badly.

---

## Section 1 — Detection Pipeline (highest scrutiny)

### Q1. Show me real YOLO output on CAM 3 — not mock.

**Why they ask:** `--mock` overlays synthetic foot paths; strict reviewers treat this as integration theater.

**Strong answer:**

> “Mock mode reads real MP4 frames but drives `TrajectoryMockPersonDetector` paths configured per camera so zone lines fire deterministically. Real YOLO is `python -m pipeline.run --camera 'CAM 3' --max-frames 50 --ingest` without `--mock`; it downloads `yolo11n.pt` and runs `YoloV11PersonDetector`. We prioritized ingest contract stability in CI; I can walk through `pipeline/detect.py` and a JSONL with real bboxes.”

**Weak answer:** “Mock is basically the same as YOLO.”

---

### Q2. Why aren’t videos in the git repo?

**Strong answer:**

> “~680 MB, license/size constraints, `.gitignore` policy. `scripts/setup_videos.py --source` copies from the challenge dataset; `validate_submission.py` fails fast if files are missing. For submission we attach pytest + validation logs and document the one-time copy step.”

**Weak answer:** “The reviewer should have the same Downloads path as me.”

---

### Q3. Why is the pipeline outside Docker?

**Strong answer:**

> “API image stays slim — no OpenCV/Ultralytics/GPU in the serving container. Pipeline is a batch worker pattern posting to the same ingest API a future GPU worker would use. Tradeoff: two-step demo, but correct separation of concerns for production.”

**Weak answer:** “We ran out of time.” (Acceptable only if followed by a concrete plan.)

---

### Q4. How accurate is staff classification?

**Strong answer:**

> “Heuristic only: dark uniform pixel ratio, backroom camera role, counter dwell. We exclude staff at emit and again in BI via `is_customer_metric_event()`. We have **no mAP or false-positive rate** on Purplle footage — I would not deploy this to payroll or HR decisions without labeled eval.”

**Weak answer:** “Staff model is implemented.” (Conflates code with quality.)

---

### Q5. Explain cross-camera Re-ID on CAM 3 → CAM 1 → CAM 5.

**Strong answer:**

> “`GlobalIdentityRegistry` assigns store-prefixed `external_track_id` using cosine-ish embedding stub, camera graph priorities, and time windows from `config.yaml`. `CrossCameraDedup` suppresses overlap false doubles (entry vs billing). Validated in unit tests and golden-day seed — **not** with a Re-ID benchmark on simultaneous real tracks.”

---

### Q6. ByteTrack is deprecated — what now?

**Strong answer:**

> “We see the ultralytics FutureWarning. Migration path: swap tracker adapter in `tracker.py` to BoT-SORT or supervision’s replacement before v0.30. Event schema unchanged.”

---

## Section 2 — Intelligence API

### Q7. I ran Docker only and `/metrics` is empty. Is the system broken?

**Strong answer:**

> “No — metrics reads `store_metrics` rollups. Fresh API has no vision events, so placeholder is correct. After pipeline ingest, run `scripts/project_demo_metrics.py` to project hourly footfall from `vision.zone.entered`. Long-term fix is a projector worker, not manual script.”

---

### Q8. Heatmap is not a heatmap — it’s a zone table.

**Strong answer:**

> “Correct. We ship zone-level visit frequency and dwell with normalized scores for MVP. Spatial grid heatmaps are in the architecture contract but deferred; zone keys map to Purplle areas (entry, aisle, billing_queue).”

---

### Q9. How does idempotent ingest work?

**Strong answer:**

> “Partial unique index on `idempotency_key`; client `event_id` dedup in batch. Re-post returns duplicate counts in 202/207 responses. Covered in `test_duplicate_ingestion` and BI validation.”

---

### Q10. Why no authentication?

**Strong answer:**

> “Challenge MVP prioritized analytics correctness and ingest contract. Architecture specifies JWT/API keys; adding middleware is isolated work. All store queries still filter by `store_id` — sufficient for demo, insufficient for multi-tenant SaaS.”

---

## Section 3 — Production Readiness

### Q11. Why SQLite in tests if production is Postgres?

**Strong answer:**

> “Speed in CI/dev. We hit real differences — naive datetimes broke stale-feed until UTC normalization. Gap acknowledged: no testcontainers Postgres job. Docker compose proves Postgres migrations on the serving path.”

---

### Q12. Where is CI?

**Strong answer:**

> “Not checked in — weakness. Local gate: `pytest --cov-fail-under=70` and `validate_submission.py`. I would add GitHub Actions running unit + compose smoke next.”

---

### Q13. `/health` returns degraded on fresh boot. Is that a bug?

**Strong answer:**

> “Intentional. DB up but no vision feed → `feed=unknown`, `stale_feed=true`, HTTP 200. Only DB down → 503 unhealthy. After pipeline ingest, `feed=fresh`, `status=ok`. Prevents silent ‘green’ when CCTV is dead.”

---

## Section 4 — Architecture honesty (trap questions)

### Q14. You claimed event-driven architecture. Where is the bus?

**Strong answer:**

> “Accurate pushback. **Implemented path:** synchronous HTTP ingest → append-only `events` table → on-read analytics. **Designed path:** Redis Streams workers in `docs/architecture/`. We should not use ‘event-driven’ without qualifying ‘event-sourced ingest, sync API.’”

---

### Q15. You claimed real-time analytics.

**Strong answer:**

> “Real-time in the sense of fresh queries after ingest — not sub-second streaming. No WebSocket, no projector lag target met. Dashboard bonus was not attempted.”

---

### Q16. Why does `api-contracts.md` describe Redis readiness?

**Strong answer:**

> “Doc drift from Phase 1 architecture. `docs/architecture/README.md` now marks implemented vs planned; full ADR rewrite is incomplete. Implemented readiness is PostgreSQL-only.”

---

## Section 5 — AI Engineering

### Q17. How much of this codebase is AI-generated?

**Strong answer:**

> “AI accelerated scaffolding — FastAPI layout, tests, architecture drafts. We owned event types, funnel rules, anomaly thresholds, session/re-entry logic, and Docker entrypoint fixes. Tests include `# PROMPT:` blocks; production modules were reviewed and edited manually.”

**Weak answer:** “Most of it.” / “None of it.” (Both trigger follow-ups.)

---

### Q18. Your `# PROMPT:` blocks look like checkbox compliance.

**Strong answer:**

> “Fair. They document intent per test file, not full chat transcripts. Deeper attribution lives in commit history and DESIGN.md AI section. I can walk file-by-file through what each test proves vs what AI drafted.”

---

## Section 6 — Dashboard bonus

### Q19. Where is the dashboard?

**Strong answer:**

> “Not submitted. Bonus pillar forfeited. API is backend-for-frontend; OpenAPI at `/docs` is the demo UI. Building React + WebSocket was out of scope after pipeline + BI.”

---

## Section 7 — Whiteboard exercises

Be ready to draw or narrate:

### Exercise A — One visitor enters CAM 3, browses CAM 1, queues CAM 5

```
MP4 → pipeline.run --mock --ingest
  → TrajectoryMockPersonDetector (CAM 3 path crosses entry_threshold)
  → SessionManager opens session
  → vision.zone.entered (entry_threshold, entrance, aisle, billing_queue)
  → POST /api/v1/events/ingest
  → GET /funnel (ENTRY → ZONE_VISIT → BILLING_QUEUE)
  → GET /heatmap (zone visit counts)
```

### Exercise B — Idempotent retry

```
Pipeline POST batch → 202 accepted
Same idempotency_keys → 202 duplicate count = N
DB row count unchanged
```

### Exercise C — Stale feed anomaly

```
No vision.frame.processed for 15+ minutes
→ GET /health: stale_feed=true
→ GET /anomalies: STALE_FEED with suggested_action
```

---

## Questions YOU should ask the reviewer (shows maturity)

1. “Is mock-over-video acceptable for integration scoring, or do you require a YOLO artifact?”
2. “Does the bonus dashboard require a UI submission or is API-only sufficient for base pass?”
3. “Should we prune unimplemented architecture docs from the submission zip?”

---

## Red-flag phrases — never say these

| Phrase | Why it fails |
|--------|--------------|
| “Fully production-ready end-to-end” | Auth, bus, CI, projector missing |
| “Real-time dashboard” | No UI, no WS |
| “YOLO validates all footfall” | Mock demo path exists |
| “Videos work out of the box on clone” | Gitignored |
| “Architecture docs match implementation” | They don’t |

---

## Pre-interview checklist (15 minutes before)

- [ ] Docker stack up; `validate_submission.py` log saved (10/10)
- [ ] `data/pipeline/events.jsonl` sample with `vision.zone.entered` lines
- [ ] One funnel + heatmap JSON response cached
- [ ] CHOICES.md open — be able to defend YOLO + ByteTrack without reading
- [ ] Honest one-liner on event-driven / real-time gaps memorized

---

## Related files

- [FINAL_SCORE.md](../FINAL_SCORE.md) — expected **97/100**
- [FINAL_GAP_ANALYSIS.md](./FINAL_GAP_ANALYSIS.md) — full requirement matrix
- [INTERVIEW_QA.md](./INTERVIEW_QA.md) — earlier ideal-answer reference (less strict tone)
