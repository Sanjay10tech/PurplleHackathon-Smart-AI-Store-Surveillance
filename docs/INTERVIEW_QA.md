# Interview Q&A — Store Intelligence

Likely follow-up questions from reviewers who have read this codebase, with concise ideal answers.

---

## Architecture & design

### Why a FastAPI monolith instead of microservices?

The team size and deployment target (Docker Compose first) do not justify network boundaries between funnel, heatmap, and anomaly logic. They share one PostgreSQL database and one release cycle. FastAPI gives OpenAPI for partners, async I/O aligned with SQLAlchemy, and thin routers over a hexagonal layout. Workers (detection, projector) are separate **processes** from the same repo, not separate microservices — we split when scaling pain is measured, not assumed.

### Why compute analytics on read instead of pre-aggregating?

We shipped on-read analytics because event volume in the pilot is unknown and the query path is easier to debug with partial data. Funnel, heatmap, and anomalies all read from `events` and `sessions` with indexed time-range filters. At scale, a projector worker will upsert `store_metrics` so dashboards stop scanning raw events — the metrics endpoint already prefers rollup rows when present.

### How does the detection pipeline relate to the API?

The pipeline in `pipeline/` is an **offline host process**: read video or synthetic frames → YOLO/mock detect → ByteTrack → zone/session logic → `EventBuilder` → HTTP POST to `/api/v1/events/ingest`. It is intentionally **not** in the API Docker image (no GPU, smaller attack surface). The API only sees validated domain events, same as a future Redis worker would publish.

### What is hexagonal architecture here in practice?

- **Domain** (`app/domain/`): pure functions — funnel calculator, heatmap aggregator, anomaly rules, staff filters. No I/O.
- **Services**: orchestrate repositories + domain; implement use cases.
- **Repositories**: SQLAlchemy; hidden behind protocols for tests.
- **Routers**: HTTP only; no business logic.

The pipeline mirrors this at the edge: detection/tracking logic is separate from HTTP ingest validation.

---

## Data model & events

### How does idempotent ingest work?

Clients may send `idempotency_key` or a stable `event_id`. The repository checks existing keys before insert. Batch ingest returns 207 with per-item `accepted` / `duplicate` / `error` counts. Re-posting the same batch yields all duplicates — verified in `test_duplicate_ingestion` and BI validation tests.

### How are sessions and re-entry handled?

The pipeline `SessionManager` opens a session on store entry (CAM 3 zone line). If the same track re-enters within a cooldown window, the session **resumes**. After cooldown, a **new** session is created with `is_reentry=True`. The funnel service counts re-entries separately from first-time entries. Cross-camera dedup uses `GlobalIdentityRegistry` with store-prefixed external IDs.

### Why flat JSON events instead of CloudEvents or Protobuf?

Retail integrations vary (POS, NVR, CV worker). One HTTP ingest contract with `event_type` + JSON `payload` minimizes client work. We kept correlation/aggregate ideas without full CloudEvents compliance. Protobuf is the escape hatch if schema churn breaks clients at scale.

### How is staff excluded from customer BI?

Vision events with `class_label=staff` or `zone_type=staff_only` are filtered by `is_customer_metric_event()` before funnel, heatmap, and anomaly aggregation. Staff tracks can still exist in raw `events` for audit; they do not inflate footfall or conversion metrics.

---

## Health, logging, observability

### What does `/health` return on a fresh Docker boot?

Database is **up** (Postgres ready). No vision events yet → `feed=unknown`, `stale_feed=true`, overall `status=degraded` with HTTP **200**. Only database failure yields `unhealthy` and HTTP **503**. This matches "fail visible, not fail silent" for an analytics platform waiting for pipeline data.

### What does `/health/ready` check?

PostgreSQL connectivity only. Redis and object storage are in the architecture roadmap but not in the Compose stack, so readiness does not fail on missing Redis.

### How is logging structured?

`structlog` with JSON in production (`LOG_JSON=true`). Middleware binds `trace_id` / `correlation_id` per request and logs `http_request_completed` with `endpoint`, `latency_ms`, `status_code`, `event_count`. Ingest and health services emit domain-specific info events. No raw bboxes or RTSP credentials in logs by default.

---

## Testing & quality

### How do you test without real CCTV or GPU?

1. **Mock pipeline** — `TrajectoryMockPersonDetector` drives deterministic trajectories through ByteTrack and zone logic.
2. **Golden retail day seed** — `tests/helpers/pipeline_event_seed.py` builds a full day of events for BI scenarios.
3. **SQLite in pytest** — fast CI; UTC normalization handles naive datetime edge cases caught in stale-feed tests.
4. **268 tests, 96.6% app coverage** — gate at 96% in `pyproject.toml`.

### What scenarios does the scenario suite cover?

Empty store, zero purchases, queue spike, conversion drop, re-entry, duplicate ingest, stale feed, all funnel stages, full BI validation (staff exclusion, idempotency, pipeline→ingest→metrics/funnel/heatmap/anomalies/health chain).

---

## Tradeoffs & future work

### Biggest technical debt?

1. **Metrics endpoint placeholder** until projector writes `store_metrics`.
2. **On-read funnel/anomaly cost** at high event volume.
3. **Architecture docs** still describe Redis/MinIO topology — README/DESIGN now mark implemented vs planned.
4. **No auth** — acceptable for challenge; required before multi-tenant SaaS.

### How would you scale to 100 stores?

- Horizontal stateless API behind a load balancer.
- Projector workers consuming Redis Streams, writing rollups.
- Partition or TimescaleDB on `events.occurred_at`.
- GPU detection nodes per region; pipeline posts to regional ingest.
- Read replicas for analytics queries; optional RLS per tenant in Postgres.

### Why YOLO + ByteTrack specifically?

Industry default for retail person detection: good community support, runs on consumer GPUs, ByteTrack gives sufficient ID continuity for dwell/funnel when combined with session rules. Alternatives (RT-DETR, cloud APIs) are documented in `CHOICES.md` with revisit triggers.

### How did AI assist development?

See **AI-Assisted Decisions** in `DESIGN.md`. AI helped scaffold FastAPI structure, pytest scenarios, and architecture drafts. Engineers owned event types, funnel stage definitions, anomaly thresholds, and Docker entrypoint fixes (CRLF → Python entrypoint). Every test file includes `# PROMPT:` attribution.

---

## Quick "whiteboard" questions

**Draw the data flow from camera to funnel API.**

```
MP4/RTSP → pipeline/run.py → detect → track → zones/sessions
    → EventBuilder → POST /events/ingest → events table
    → GET /stores/{id}/funnel → FunnelService → domain calculator
```

**What happens if the pipeline sends duplicate events?**

Ingest returns duplicate count; DB unique constraints on idempotency keys prevent double rows; funnel session logic dedupes by session/external_track_id where applicable.

**How do you detect a stale CCTV feed?**

`HealthService` and anomaly `STALE_FEED` both compare `now - last vision.frame.processed|zone.entered` against `HEALTH_STALE_FEED_MINUTES` (default 15).

**What would you change with one more week?**

Analytics projector for metrics, API key auth, and a slim pipeline Docker profile for demo ingest in Compose without GPU.
