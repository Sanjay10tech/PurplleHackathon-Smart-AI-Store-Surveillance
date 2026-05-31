# Repository Structure & Module Boundaries

## Complete Folder Tree

```
Smart-AI-StoreSurveillance/
│
├── docker/
│   ├── docker-compose.yml              # Core stack: api, workers, postgres, redis, minio
│   ├── docker-compose.dev.yml          # Dev overrides: hot reload, debug ports
│   ├── docker-compose.test.yml         # CI integration test stack
│   ├── Dockerfile.api                  # Multi-stage API image
│   ├── Dockerfile.worker               # Shared worker base image
│   └── init/                           # DB init scripts (extensions, roles)
│
├── docs/
│   ├── architecture/                   # This documentation set
│   └── adr/                            # Architecture Decision Records (numbered)
│
├── alembic/
│   ├── versions/                       # Sequential migrations
│   └── env.py                          # Migration runtime config
│
├── src/
│   └── store_intelligence/
│       │
│       ├── main.py                     # FastAPI application factory
│       ├── config/
│       │   ├── settings.py             # Pydantic Settings (env-driven)
│       │   └── logging.yaml            # Logging config reference
│       │
│       ├── domain/                     # ═══ INNER CORE (no infra imports) ═══
│       │   ├── models/                 # Pure domain entities & value objects
│       │   │   ├── store.py
│       │   │   ├── camera.py
│       │   │   ├── zone.py
│       │   │   ├── track.py
│       │   │   ├── detection.py
│       │   │   └── analytics.py
│       │   ├── events/                 # Domain event dataclasses / schemas
│       │   │   ├── base.py
│       │   │   ├── ingestion.py
│       │   │   ├── vision.py
│       │   │   └── analytics.py
│       │   ├── interfaces/             # Ports (abstract base classes)
│       │   │   ├── frame_source.py     # IFrameSource
│       │   │   ├── detector.py         # IDetector
│       │   │   ├── tracker.py          # ITracker
│       │   │   ├── zone_analyzer.py    # IZoneAnalyzer
│       │   │   ├── event_bus.py        # IEventPublisher, IEventConsumer
│       │   │   ├── repositories.py     # IStoreRepo, ITrackRepo, etc.
│       │   │   └── storage.py          # IObjectStorage, IMediaStore
│       │   └── exceptions.py
│       │
│       ├── application/                # ═══ USE CASES & ORCHESTRATION ═══
│       │   ├── use_cases/
│       │   │   ├── register_camera.py
│       │   │   ├── ingest_frame_batch.py
│       │   │   ├── process_detection_result.py
│       │   │   └── query_analytics.py
│       │   ├── services/
│       │   │   ├── ingestion_service.py
│       │   │   ├── analytics_service.py
│       │   │   └── realtime_service.py
│       │   └── handlers/               # Event handler registry
│       │       ├── ingestion_handlers.py
│       │       ├── vision_handlers.py
│       │       └── analytics_handlers.py
│       │
│       ├── infrastructure/             # ═══ ADAPTERS (implements ports) ═══
│       │   ├── db/
│       │   │   ├── session.py          # Async SQLAlchemy engine
│       │   │   ├── models/             # ORM models (separate from domain)
│       │   │   └── repositories/       # Repository implementations
│       │   ├── messaging/
│       │   │   ├── redis_streams.py
│       │   │   └── event_serializer.py
│       │   ├── pipeline/               # CV pipeline adapters (STUB until dataset)
│       │   │   ├── stub_detector.py    # No-op / synthetic for tests
│       │   │   ├── stub_tracker.py
│       │   │   └── factory.py          # Wires real YOLO+ByteTrack when ready
│       │   ├── storage/
│       │   │   ├── s3_client.py
│       │   │   └── minio_adapter.py
│       │   └── observability/
│       │       ├── logging.py          # structlog setup
│       │       ├── metrics.py          # Prometheus counters/histograms
│       │       └── tracing.py          # OpenTelemetry hooks
│       │
│       ├── api/                        # ═══ HTTP / WS DELIVERY ═══
│       │   ├── v1/
│       │   │   ├── router.py
│       │   │   ├── routes/
│       │   │   │   ├── health.py
│       │   │   │   ├── stores.py
│       │   │   │   ├── cameras.py
│       │   │   │   ├── zones.py
│       │   │   │   ├── events.py
│       │   │   │   ├── analytics.py
│       │   │   │   ├── ingestion.py
│       │   │   │   └── websocket.py
│       │   │   ├── schemas/            # Pydantic API DTOs (request/response)
│       │   │   └── deps.py             # DI: db session, auth, correlation_id
│       │   └── middleware/
│       │       ├── correlation.py
│       │       ├── request_logging.py
│       │       └── error_handler.py
│       │
│       └── workers/                    # ═══ ASYNC PROCESS ENTRYPOINTS ═══
│           ├── ingestion_worker.py
│           ├── detection_worker.py
│           ├── analytics_worker.py
│           └── cli.py                  # Typer CLI for one-off jobs
│
├── tests/
│   ├── unit/                           # Domain + use cases (no I/O)
│   ├── integration/                    # DB, Redis, API with testcontainers
│   ├── contract/                       # API OpenAPI + event schema validation
│   ├── pipeline/                       # Stub pipeline integration tests
│   └── e2e/                            # Full compose stack scenarios
│
├── scripts/
│   ├── seed_dev_data.py                # Synthetic stores/cameras (no real CCTV)
│   ├── replay_events.py                # Event replay for debugging
│   └── export_openapi.py
│
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
└── Makefile                            # compose up, migrate, test shortcuts
```

## Module Boundary Rules

### Dependency Direction (Strict)

```
api ──► application ──► domain ◄── infrastructure
workers ──► application ──► domain ◄── infrastructure
```

| Layer | May Import | Must NOT Import |
|-------|------------|-----------------|
| `domain` | stdlib, typing, pydantic (value objects only) | `infrastructure`, `api`, FastAPI, SQLAlchemy, cv2, ultralytics |
| `application` | `domain` | `infrastructure` concrete classes (use DI) |
| `infrastructure` | `domain`, third-party libs | `api` |
| `api` | `application`, `domain` (DTO mapping only) | ORM models directly in routes |
| `workers` | `application`, `infrastructure` (composition root) | `api` |

### Composition Root

- **`main.py`** (API) and **`workers/*.py`** are the only places that wire concrete adapters to interfaces.
- A **`PipelineFactory`** in `infrastructure/pipeline/factory.py` selects stub vs. real implementations via config (`PIPELINE_MODE=stub|yolo_bytetrack`).

### Key Abstractions (Ports)

| Port | Purpose | Default Adapter | Future Adapter |
|------|---------|-----------------|----------------|
| `IFrameSource` | Yield normalized frames + metadata | File/RTSP readers | NVR SDK, S3 video |
| `IDetector` | Bounding boxes + class IDs + confidence | `StubDetector` | YOLOv8/v11 |
| `ITracker` | Associate detections → track IDs | `StubTracker` | ByteTrack |
| `IZoneAnalyzer` | Map tracks to configured zones | Polygon intersection | Calibrated homography |
| `IEventPublisher` | Emit domain events | Redis Streams | Kafka/RabbitMQ |
| `IAnalyticsRepository` | Persist/query aggregates | PostgreSQL | + TimescaleDB hypertables |

### Package Visibility

- **`domain/events/`** defines canonical event shapes (source of truth).
- **`infrastructure/messaging/event_serializer.py`** handles JSON encoding, schema version headers.
- **`api/schemas/`** defines HTTP DTOs — never identical to domain events (explicit mapping prevents API coupling to internal event evolution).

## Configuration Boundaries

All environment-specific values flow through `config/settings.py`:

```
DATABASE_URL, REDIS_URL, S3_ENDPOINT, PIPELINE_MODE,
LOG_LEVEL, EVENT_SCHEMA_VERSION, TENANT_ID (optional default)
```

No magic constants for camera resolution, FPS, or class labels in application code — these live in DB config or pipeline YAML loaded at runtime.
