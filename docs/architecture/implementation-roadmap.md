# Implementation Roadmap

Phased delivery plan. Each phase produces a deployable, testable increment. No phase assumes the CCTV dataset except where noted.

---

## Phase 0: Foundation (Week 1–2)

**Goal:** Empty repo → running Compose stack with health checks and migrations.

| Task | Deliverable | Exit Criteria |
|------|-------------|---------------|
| Initialize `pyproject.toml` | Dependencies pinned (FastAPI, SQLAlchemy 2, asyncpg, redis, structlog, pydantic-settings) | `pip install -e .` succeeds |
| Docker Compose | postgres, redis, minio, api | `docker compose up` → `/health` 200 |
| Alembic setup | Initial migration: tenants, stores, cameras | `alembic upgrade head` clean |
| Config module | Pydantic Settings + `.env.example` | All services read shared config |
| Logging | structlog JSON + correlation middleware stub | Logs include `correlation_id` |
| CI skeleton | lint + unit test job | Green on empty test suite |

**Risk:** None — standard scaffolding.

---

## Phase 1: Domain Core & Ports (Week 2–3)

**Goal:** Pure domain layer + interface definitions; no CV dependencies.

| Task | Deliverable |
|------|-------------|
| Domain entities | Store, Camera, Zone, Track, Detection, IngestJob |
| Domain events | All event types from `events.md` as dataclasses |
| Port interfaces | `IDetector`, `ITracker`, `IFrameSource`, `IZoneAnalyzer`, `IEventPublisher`, repositories |
| Stub adapters | `StubDetector`, `StubTracker`, `FileFrameSource`, `PolygonZoneAnalyzer` |
| `PipelineFactory` | Returns stub stack when `PIPELINE_MODE=stub` |
| Unit tests | Domain + contract test base classes |

**Exit criteria:** `pytest tests/unit` green; stub pipeline processes synthetic frame in-memory test.

---

## Phase 2: Persistence & Repositories (Week 3–4)

**Goal:** Full database schema and repository implementations.

| Task | Deliverable |
|------|-------------|
| Migrations | All tables from `database-schema.md` |
| ORM models | Separate from domain; mapping in repositories |
| Repositories | Store, Camera, Zone, IngestJob, Track, Detection, AnalyticsRollup, DomainEvent |
| Tenant scoping | Base repository filter |
| Integration tests | testcontainers PostgreSQL |

**Exit criteria:** CRUD integration tests pass; tenant isolation verified.

---

## Phase 3: Event Bus & Workers (Week 4–5)

**Goal:** Async pipeline with Redis Streams.

| Task | Deliverable |
|------|-------------|
| Redis Streams adapter | Publish, consume, consumer groups, ack |
| Event serializer | Envelope + schema version |
| Ingestion worker | Job → frames → MinIO → `ingestion.frame.ready` |
| Detection worker | Stub pipeline → `vision.*` events |
| Analytics worker | Rollups → `analytics.rollup.updated` |
| Event projector | All events → `domain_events` |
| DLQ handler | 3 retries → `si:dlq` |
| Idempotency | Keys enforced in handlers |

**Exit criteria:** E2E test: POST job → footfall metric available via direct DB query.

---

## Phase 4: REST API (Week 5–6)

**Goal:** Full v1 API per `api-contracts.md`.

| Task | Deliverable |
|------|-------------|
| Auth | JWT + API keys (minimal RBAC) |
| Routes | stores, cameras, zones, class-labels, ingestion, events, analytics |
| Error handling | RFC 7807 Problem Details |
| OpenAPI export | `docs/openapi/v1.yaml` |
| Contract tests | schemathesis smoke |
| Pagination | Cursor implementation |

**Exit criteria:** All documented endpoints return correct shapes; OpenAPI validates.

---

## Phase 5: Real-time & Observability (Week 6–7)

**Goal:** Production operability basics.

| Task | Deliverable |
|------|-------------|
| WebSocket | `/ws/analytics/{store_id}` with subscribe |
| Redis pub/sub | Realtime fanout from analytics worker |
| Prometheus metrics | Frame latency, job counts, DLQ depth |
| Readiness probes | API + worker health endpoints |
| Grafana dashboard | Optional compose profile |
| OpenTelemetry | Trace propagation (optional) |

**Exit criteria:** WebSocket e2e test receives rollup within 5s of job processing.

---

## Phase 6: Dataset Integration — CV Pipeline (Week 7–10)

**Trigger:** CCTV dataset available on disk or S3.

**Goal:** Plug in YOLO + ByteTrack without changing event contracts.

| Task | Deliverable |
|------|-------------|
| Profile dataset | Resolution, FPS, format, label taxonomy doc |
| Populate `class_labels` | Seed script from model metadata |
| `YoloDetector` adapter | Implements `IDetector`; lazy import ultralytics |
| `ByteTrackAdapter` | Implements `ITracker` |
| GPU Dockerfile | `Dockerfile.worker-gpu` + compose override |
| Calibrate zones | Pilot camera polygons in normalized space |
| Contract tests | `YoloDetectorTests` extends `DetectorContractTests` |
| Benchmark | Frames/sec, p95 latency report |

**Exit criteria:** Real video ingest → footfall within 10% of manual count on sample clip.

**Rollback:** Set `PIPELINE_MODE=stub` — zero API changes.

---

## Phase 7: Hardening & Production Prep (Week 10–12)

| Task | Deliverable |
|------|-------------|
| Retention jobs | Frame cleanup, detection purge |
| Export jobs | CSV/Parquet async export |
| Rate limiting | Redis token bucket |
| Security audit | Tenant isolation, secret redaction |
| Load test | k6 analytics queries |
| Runbook | Ops doc: DLQ replay, camera error recovery |
| ADR updates | Document production broker/DB choices |

**Exit criteria:** 24-hour soak test on staging without memory leak or DLQ growth.

---

## Phase 8: Scale Path (Future)

Not scheduled — implement when metrics demand.

| Trigger | Action |
|---------|--------|
| >10M detections/month | TimescaleDB hypertables |
| >50k events/sec | Kafka migration ADR |
| Multi-region | Read replicas, S3 cross-region |
| K8s requirement | Helm chart, HPA on detection workers |
| Privacy regulation | `IFrameProcessor` blur port before storage |

---

## Milestone Timeline (Visual)

```
Week:  1    2    3    4    5    6    7    8    9   10   11   12
       ├────┤
       Ph0 Foundation
            ├────┤
            Ph1 Domain + Ports
                 ├────┤
                 Ph2 Persistence
                      ├────┤
                      Ph3 Event Bus + Workers
                           ├────┤
                           Ph4 REST API
                                ├────┤
                                Ph5 Real-time + Obs
                                     ├──────────┤
                                     Ph6 CV Pipeline (dataset)
                                              ├────┤
                                              Ph7 Hardening
```

---

## Definition of Done (Per Phase)

- [ ] Code merged to `main`
- [ ] Tests pass in CI (appropriate level for phase)
- [ ] Architecture doc updated if contracts changed
- [ ] `.env.example` reflects new config
- [ ] No secrets committed
- [ ] README updated with run instructions for new capability

---

## Team Parallelization

| Stream A | Stream B |
|----------|----------|
| Domain + API (Ph 1, 4) | Infrastructure + DB (Ph 2) |
| Workers + events (Ph 3) | Observability (Ph 5) |
| CV pipeline (Ph 6) | QA + e2e (continuous) |

Phases 1–2 can overlap after day 3. Phase 6 blocked on dataset only.

---

## First Implementation PR Suggestion

When coding begins, first PR should contain:

1. Repo scaffold (folders from `repository-structure.md`)
2. `pyproject.toml` + Docker Compose (postgres, redis, minio, api stub)
3. Domain ports + stub detector
4. Single health endpoint
5. Initial Alembic migration (tenants, stores, cameras)

This matches **Phase 0 + Phase 1 starter** — demoable in one review.
