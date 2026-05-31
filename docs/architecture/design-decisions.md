# Design Decisions & Tradeoffs

Architecture Decision Records (ADRs) for the Store Intelligence System. Each entry documents the decision, alternatives considered, and consequences.

---

## ADR-001: Hexagonal Architecture with Explicit CV Pipeline Ports

**Status:** Accepted

**Context:** CCTV dataset unknown. YOLO + ByteTrack integration deferred. System must remain testable and deployable without GPU or training data.

**Decision:** Define `IFrameSource`, `IDetector`, `ITracker`, `IZoneAnalyzer` as domain ports. Ship stub adapters. Wire real implementations via `PipelineFactory` + `PIPELINE_MODE` env.

**Alternatives:**
| Option | Rejected Because |
|--------|------------------|
| Build YOLO first, refactor later | Blocks API/DB/analytics progress; couples design to model output |
| Single `IPipeline` god interface | Hard to unit test; can't swap tracker independently |
| Microservice per pipeline stage | Premature ops overhead for initial team size |

**Consequences:**
- (+) Full stack runnable day one with synthetic data
- (+) Contract tests lock interface before real CV work
- (−) Extra abstraction layer; factory wiring must stay in composition root only

---

## ADR-002: Redis Streams as Phase-1 Message Broker

**Status:** Accepted

**Context:** Event-driven architecture required. Team size small. Docker Compose deployment.

**Decision:** Redis Streams with consumer groups for `si:ingestion`, `si:vision`, `si:analytics`.

**Alternatives:**
| Option | Tradeoff |
|--------|----------|
| RabbitMQ | Stronger routing; extra container; team less familiar |
| Kafka | Best throughput; heavy for MVP |
| In-process asyncio queues | No cross-container decoupling; fails compose multi-worker model |
| PostgreSQL LISTEN/NOTIFY | Poor backlog handling; not designed for high fanout |

**Consequences:**
- (+) Redis already needed for cache + pub/sub + rate limiting
- (+) Low operational footprint
- (−) Stream memory limits require monitoring; migration to Kafka documented in roadmap
- (−) At-least-once delivery → idempotency mandatory (accepted)

---

## ADR-003: Append-Only domain_events Table + Projector Worker

**Status:** Accepted

**Context:** Need audit trail, replay capability, and decoupled read models.

**Decision:** Dedicated `worker-event-projector` consumes all streams and inserts into `domain_events`. Analytics writes to separate rollup tables.

**Alternatives:**
| Option | Tradeoff |
|--------|----------|
| Events only in streams (no DB) | No historical query via API; replay limited by retention |
| Event sourcing as sole storage | Complex projections; overkill for MVP analytics |
| Dual-write from each handler | Race conditions; inconsistent audit log |

**Consequences:**
- (+) Single source of truth for "what happened"
- (+) Handlers stay focused; projection lag acceptable (<1s)
- (−) Storage growth; retention policy required
- (−) Projector is critical path for audit — monitor lag

---

## ADR-004: JSONB for Camera/Zone Configuration (Not Fixed Schema)

**Status:** Accepted

**Context:** Unknown camera resolutions, NVR vendors, zone semantics until dataset and pilot stores arrive.

**Decision:** Store `config`, `calibration`, `polygon` as JSONB with Pydantic validation at application boundary. No PostgreSQL enums for class names or zone types.

**Alternatives:**
| Option | Tradeoff |
|--------|----------|
| Strict relational schema now | Migration churn when reality differs |
| Fully schemaless document DB | Lose JOIN analytics; add second database |

**Consequences:**
- (+) Pilot stores onboard without migrations
- (+) Class label mapping table bridges model output → business semantics
- (−) JSONB queries slower; mitigated by rollups for hot paths
- (−) Validation logic must be rigorous in application layer

---

## ADR-005: Normalized Coordinates for Zones and Bounding Boxes

**Status:** Accepted

**Context:** Cameras may differ in resolution; dataset FPS and dimensions unknown.

**Decision:** All spatial data stored in 0.0–1.0 normalized space relative to frame dimensions. Conversion at pipeline boundary.

**Alternatives:**
| Option | Tradeoff |
|--------|----------|
| Pixel coordinates | Breaks when resolution changes |
| World coordinates (meters) | Requires calibration not available yet |

**Consequences:**
- (+) Resolution-agnostic zones survive camera upgrades
- (−) Homography-based floor plans need future `calibration` JSONB extension
- (−) Integer rounding in small bboxes — document epsilon in zone analyzer

---

## ADR-006: Separate Domain Models from ORM Models

**Status:** Accepted

**Context:** Keep domain pure for testing; avoid SQLAlchemy leaking into use cases.

**Decision:** `domain/models/` (dataclasses/Pydantic) distinct from `infrastructure/db/models/` (SQLAlchemy). Repositories map between them.

**Alternatives:**
| Option | Tradeoff |
|--------|----------|
| SQLAlchemy models everywhere | Faster to write; domain tests need DB |
| Single Pydantic model shared | ORM lazy-loading leaks into API |

**Consequences:**
- (+) Unit tests stay fast; clear boundaries
- (−) Mapping boilerplate — acceptable for long-lived system

---

## ADR-007: Cursor Pagination (Not Offset)

**Status:** Accepted

**Context:** Event and detection lists grow unbounded.

**Decision:** API list endpoints use opaque cursor pagination.

**Alternatives:** Offset pagination — simple but O(n) degradation on large tables.

**Consequences:**
- (+) Stable performance under growth
- (−) Cannot jump to arbitrary page number — acceptable for analytics APIs

---

## ADR-008: FastAPI Monolith Gateway + Separate Worker Processes

**Status:** Accepted

**Context:** Real-time WebSocket + REST; detection is CPU/GPU intensive.

**Decision:** Single codebase; `api` and `worker-*` are different entrypoints from same image (or shared base).

**Alternatives:**
| Option | Tradeoff |
|--------|----------|
| API-only monolith with background tasks | Detection blocks event loop; no GPU isolation |
| Full microservices repo per service | Duplicated domain code or shared package complexity |

**Consequences:**
- (+) One deploy artifact; shared domain logic
- (+) Workers scale independently in compose/K8s
- (−) Must avoid importing heavy CV libs in API process — lazy import in detection worker only

---

## ADR-009: Stub Pipeline as Default in Development

**Status:** Accepted

**Context:** Developers may not have GPU or dataset.

**Decision:** `PIPELINE_MODE=stub` default in `.env.example`. CI always runs stub.

**Consequences:**
- (+) Onboarding friction minimized
- (−) Risk of stub/real behavior drift — mitigated by shared contract tests

---

## ADR-010: WebSocket Real-time via Redis Pub/Sub Fanout

**Status:** Accepted

**Context:** Dashboard needs sub-second metric updates without polling.

**Decision:** Analytics worker publishes to Redis channel `si:rt:{store_id}`. API process subscribes and pushes to WebSocket clients.

**Alternatives:**
| Option | Tradeoff |
|--------|----------|
| Client polls REST | Higher latency and load |
| Dedicated realtime service (Ably/Pusher) | Cost; external dependency |
| SSE instead of WebSocket | One-way sufficient but WebSocket allows subscribe mutations |

**Consequences:**
- (+) Simple; reuses Redis
- (−) API horizontal scaling requires each instance to subscribe — acceptable at expected scale; Redis adapter pattern if needed

---

## ADR-011: Multi-Tenant from Day One

**Status:** Accepted

**Context:** Product may serve multiple retail chains.

**Decision:** `tenant_id` on all scoped tables; repository base class enforces filter.

**Alternatives:** Single-tenant MVP — cheaper now, expensive migration later.

**Consequences:**
- (+) No rewrite for SaaS
- (−) Slightly more complex auth — acceptable

---

## ADR-012: Idempotency Keys on Ingestion and Vision Events

**Status:** Accepted

**Context:** At-least-once delivery from Redis Streams.

**Decision:** Handlers check `idempotency_key` before side effects; unique index on `domain_events`.

**Consequences:**
- (+) Safe retries and horizontal workers
- (−) Key design must be stable — documented in events.md

---

## Summary Tradeoff Matrix

| Dimension | Chosen | Sacrificed |
|-----------|--------|------------|
| Time-to-first-demo | Stub pipeline + Compose | Real detection accuracy |
| Flexibility | JSONB config, string zone types | Query performance on raw JSON |
| Ops simplicity | Redis Streams, Compose | Kafka-grade throughput |
| Code clarity | Hexagonal layers | More files and mapping |
| Auditability | Full event log | Storage cost |
| Real-time latency | Redis pub/sub | Strong ordering guarantees to clients |

---

## Open Questions (Resolve When Dataset Arrives)

1. **Class taxonomy** — Map YOLO COCO classes vs. custom retail model → populate `class_labels`.
2. **Target FPS** — Ingestion sampling rate per camera type.
3. **Batch vs. stream** — NVR provides files vs. live RTSP; may add `IFrameSource` implementations only.
4. **GPU sizing** — Profile YOLO model size (n/s/m) vs. latency SLO.
5. **Privacy** — Face blurring before storage if required by jurisdiction (new `IFrameProcessor` port?).

These are explicitly **not** decided prematurely.
