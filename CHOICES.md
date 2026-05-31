# Engineering Choices

Architecture Decision Records (ADRs) for Store Intelligence Phase 1. Each decision follows: **Context → Options Considered → Decision → Tradeoffs → Future Improvements**.

Round 2 scope: offline CCTV + POS → business metrics via ingested events and on-read SQL aggregation.

---

## A. Model Selection

### Context

The detection pipeline must locate **persons** in fixed retail CCTV (Brigade Road MP4s), run on reviewer laptops (CPU acceptable), and integrate with Python 3.11 without a custom training cycle for Phase 1. Latency matters less than accuracy on sampled frames because processing is **offline batch**, not live RTSP.

Requirements:

- Person bounding boxes suitable for zone polygon tests
- Stable enough IDs for ByteTrack across consecutive frames
- Reproducible weights and documented version for submission evidence

### Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **Ultralytics YOLOv11** | Strong COCO person class; pip-installable; GPU/CPU; active docs | General detector, not retail-specific; license review for commercial use |
| **YOLOv8 / YOLOv5** | Mature ecosystem | Older; v11 chosen for current Ultralytics default |
| **Detectron2 / MMDetection** | Research-grade accuracy | Heavier install; steeper reviewer setup |
| **OpenCV HOG + CSRT** | No GPU; tiny deps | Poor accuracy in crowded retail scenes |
| **Cloud vision API** | No local GPU | Network dependency; cost; not offline-first |
| **Mock trajectories (`--mock`)** | Fast CI/dev | Not real CV — must never be presented as YOLO output |

### Decision

**Ultralytics YOLOv11 (`yolo11n.pt` nano variant)** for person detection, paired with **ByteTrack** for within-camera tracking.

- Default pipeline mode: `yolo` (`PIPELINE_MODE=yolo` in Docker worker)
- Mock mode reserved for CI shortcuts and unit tests; events stamped `detector_mode=mock`
- Committed bootstrap JSONL (`data/reviewer/yolo_bootstrap_events.jsonl`) provides reviewer-ready data without 680 MB video download

### Tradeoffs

| Gain | Cost |
|------|------|
| Fast integration (`ultralytics` pip package) | Nano model misses occluded/distant shoppers |
| Reproducible pretrained weights | No fine-tune on Brigade camera angles |
| CPU-viable with frame stride | Real-time on all five full videos still slow without GPU |
| Clear separation from mock via metadata | Reviewers must check `detector_mode` / provenance bar |

### Future Improvements

- Fine-tune YOLO on Brigade footage for angle/occlusion
- Upgrade to `yolo11s/m` when GPU workers are available
- Add staff/uniform class via custom dataset (Phase 2)
- TensorRT / ONNX export for edge deployment
- Ensemble with lightweight pose model for zone dwell quality

---

## B. Event Schema Design

### Context

Vision pipeline output must be **ingested**, **deduplicated**, **queried for BI** (funnel, heatmap, anomalies), and **auditable** for reviewers. Events arrive from pipeline POST, bootstrap JSONL, and future POS/webhook sources.

Requirements:

- Idempotent ingest (retries must not double-count)
- Flexible payload for evolving CV metadata
- SQL-friendly aggregation by store, time, zone, track ID
- No premature microservice event bus in Phase 1

### Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **Flat table + `event_type` string** | Simple ingest; one Alembic migration path; easy JSONB queries | No compile-time schema per type beyond Pydantic at boundary |
| **Normalized tables per event type** | Strict SQL types | Migration explosion; painful pipeline iteration |
| **Avro/Protobuf + schema registry** | Strong contracts at scale | Overkill for Phase 1 monolith |
| **Nested domain objects only (no event log)** | Less storage | Loses audit trail; cannot replay funnel logic |
| **CloudEvents envelope** | Interop standard | Extra wrapper noise for internal MVP |

### Decision

**Single `events` table** with:

- Discriminator column `event_type` (`vision.zone.entered`, `vision.zone.exited`, `vision.frame.processed`, …)
- `payload` JSONB for CV-specific fields (`external_track_id`, `zone_type`, `detector_mode`, `source_video`, `is_reentry`, …)
- `aggregate_type` + `aggregate_id` for zone/session linkage
- **`idempotency_key`** unique constraint for safe retries

Pydantic validators at ingest enforce per-type required fields; domain calculators read payload keys explicitly.

### Tradeoffs

| Gain | Cost |
|------|------|
| One ingest endpoint for all vision events | JSONB queries less ergonomic than typed columns |
| Easy bootstrap from JSONL | Schema drift requires careful Pydantic + migration discipline |
| Full audit log for reviewer lineage | Large payloads (frame.processed with tracks) increase row size |
| Idempotent pipeline replays | Must design keys carefully (`cam-frame-zone-track`) |

### Future Improvements

- Generated JSON Schema catalog published at `/api/v1/schemas/events`
- Postgres partitioning by `occurred_at` month
- Outbox pattern → Redis Streams when ingest rate exceeds single-writer comfort
- Optional typed materialized columns for hot keys (`external_track_id`, `zone_key`) via generated columns or indexer
- CloudEvents wrapper for external integrators only

---

## C. API Design Decision

### Context

Phase 1 exposes **REST BI APIs**, **batch event ingest**, **health probes**, **WebSocket live snapshots**, and a **static dashboard**. Reviewers run locally via Docker; CI must spin up uvicorn quickly. Team skill set is Python-first.

Requirements:

- OpenAPI docs for Round 2 API evaluation
- Async DB access (PostgreSQL via asyncpg)
- Low ceremony for Pydantic request/response models
- Single deployable artifact with pipeline as optional worker

### Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **FastAPI** | Async native; automatic OpenAPI; Pydantic v2 | Less opinionated than Django for admin CRUD |
| **Django + DRF** | Batteries included ORM/admin | Sync-first legacy; heavier for pure API |
| **Flask + manual OpenAPI** | Minimal | No async story; more boilerplate |
| **Node/NestJS** | Good for real-time | Splits stack from Python pipeline |
| **gRPC only** | Efficient internal RPC | Poor reviewer ergonomics without REST gateway |

### Decision

**FastAPI** as the HTTP/WebSocket layer:

- Routers under `app/routers/` (`events`, `stores`, `health`, `reviewer`, `ws`)
- Services orchestrate repositories; domain logic stays pure in `app/domain/`
- **`X-API-Key`** auth for store endpoints; `REVIEWER_MODE` for demo key acceptance
- OpenAPI at `/docs`; reviewer guide at `/reviewer/api`

### Tradeoffs

| Gain | Cost |
|------|------|
| `/docs` satisfies API documentation criterion | API key auth is not production OAuth |
| Async SQLAlchemy fits ingest + concurrent dashboard reads | Single-process uvicorn default — no horizontal scale in Compose |
| Pydantic validation matches event schema boundary | WebSocket auth mirrors REST but lacks full JWT story |
| Fast CI startup | FastAPI ecosystem less mature than Django for admin UI |

### Future Improvements

- OAuth2/JWT with store-scoped roles
- API rate limiting (Redis sliding window)
- GraphQL read layer for dashboard if endpoint proliferation continues
- Versioned OpenAPI export in CI artifacts
- Separate read replicas / caching layer behind same FastAPI app

---

## Cross-Cutting: CCTV Events → Business Metrics

This section ties the three decisions together for reviewers evaluating **business value**.

### Pipeline (YOLO + flat events)

1. YOLO detects person → ByteTrack assigns `external_track_id`
2. Zone mapper emits `vision.zone.entered` / `exited` with `zone_type`
3. Flat ingest persists rows → auditable event log

### Analytics (FastAPI + SQL)

4. **Footfall / unique visitors** — distinct tracks from zone events (+ nested frame tracks)
5. **Heatmap** — per-zone visit counts and dwell from enter/exit pairs
6. **Funnel** — first-touch stage progression ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE
7. **Conversion rate** — `PURCHASE.count / ENTRY.count` (dashboard); per-stage rates in funnel API
8. **POS revenue** — `transactions` table (all CSV orders, independent of linkage)
9. **Anomalies** — compare current window to baseline (queue spike, conversion drop, dead zone, stale feed)

### Re-entry handling

- Pipeline: cooldown → `is_reentry=true` on payload
- Funnel: `re_entry_count` per stage without incrementing first-touch `count`
- Dashboard: Re-Entries KPI aggregates re-entry signals

### Edge cases (honest)

| Case | Outcome |
|------|---------|
| Bootstrap JSONL only | Valid metrics; feed shows stale (batch) |
| `--mock` ingest | Metrics compute correctly but `detector_mode=mock` — not YOLO proof |
| 24 POS orders, 1 linked purchase | POS KPI = 24; funnel PURCHASE = 1 — different definitions |
| Track without store entry | May count as visitor but skip ENTRY stage |
| Re-entry after cooldown | Visible in re_entry_count, not double-counted in conversion numerator |

---

## Phase 1 vs Phase 2 Summary

| Topic | Phase 1 (shipped) | Phase 2 (planned) |
|-------|-------------------|-------------------|
| Detection | YOLOv11 offline / bootstrap JSONL | Live RTSP + GPU fleet |
| Events | Postgres flat log | + Redis Streams, schema registry |
| API | FastAPI + API key | + JWT, rate limits, multi-tenant |
| Linkage | Heuristic time window | Receipt-level integration |
| Anomalies | Rule-based | ML seasonal models |

---

## Related Documents

- [DESIGN.md](./DESIGN.md) — Full system design and diagrams
- [README.md](./README.md) — Installation, endpoints, reviewer flow
- [docs/POS_CCTV_LINKAGE.md](./docs/POS_CCTV_LINKAGE.md) — Purchase linkage detail
- [REALITY_AUDIT_REPORT.md](./REALITY_AUDIT_REPORT.md) — Data lineage verification
