# Testing Strategy

## Testing Pyramid

```
                    ┌─────────┐
                    │   E2E   │  Few: full compose, happy path + failure
                   ┌┴─────────┴┐
                   │ Integration│  DB, Redis, API, event bus
                  ┌┴───────────┴┐
                  │   Contract   │  OpenAPI + event schema snapshots
                 ┌┴─────────────┴┐
                 │     Unit       │  Domain, use cases, handlers (mocked ports)
                 └───────────────┘
```

## Test Directory Layout

```
tests/
├── unit/
│   ├── domain/              # Entity rules, zone intersection math
│   ├── application/         # Use cases with fake repositories
│   └── infrastructure/      # Serializers, redaction processors
├── integration/
│   ├── api/                 # TestClient + real DB (testcontainers)
│   ├── repositories/        # CRUD against PostgreSQL
│   ├── messaging/           # Redis Streams publish/consume
│   └── pipeline/            # Stub pipeline end-to-end in-process
├── contract/
│   ├── test_openapi.py      # Response matches published spec
│   └── test_event_schemas.py # Payload validates against JSON Schema
├── pipeline/
│   └── test_stub_detector.py # Interface compliance tests
└── e2e/
    ├── test_ingest_to_analytics.py
    └── test_websocket_realtime.py
```

## Layer-Specific Strategy

### Unit Tests (Fast, No I/O)

**Target:** `domain/`, `application/`

| Area | Example Tests |
|------|---------------|
| Zone intersection | Point-in-polygon, normalized coords |
| Event envelope | Required fields, version parsing |
| Idempotency keys | Deterministic generation |
| Use cases | `ProcessDetectionResult` with fake `IAnalyticsRepository` |
| Dwell calculation | Enter/exit → dwell_ms |

**Tools:** `pytest`, `pytest-asyncio`, manual fakes (no heavy mock frameworks).

**Coverage target:** 90%+ on `domain/` and `application/`.

### Integration Tests (Testcontainers)

**Target:** `infrastructure/`, `api/`

| Suite | Containers | Scenarios |
|-------|------------|-----------|
| `test_repositories` | PostgreSQL | Migrations apply, CRUD, tenant isolation |
| `test_redis_streams` | Redis | Consumer groups, ack, DLQ simulation |
| `test_api_stores` | PostgreSQL + Redis | Full HTTP round-trip |
| `test_ingestion_worker` | All three | Job created → frames in MinIO |

**Tools:** `testcontainers-python`, `httpx.AsyncClient`, Alembic migrate in fixture.

**CI:** GitHub Actions job with Docker-in-Docker; `docker-compose.test.yml`.

### Contract Tests

**Purpose:** Prevent API and event drift without coupling to implementation details.

| Contract | Validation |
|----------|------------|
| OpenAPI 3.1 | `schemathesis` or `openapi-spec-validator` against exported spec |
| Event schemas | JSON Schema files in `docs/architecture/schemas/events/` |
| Backward compat | New event fields must be optional (automated check) |

Snapshot policy: review intentional breaking changes in PR.

### Pipeline Interface Tests

**Purpose:** Ensure future YOLO/ByteTrack adapters satisfy ports before dataset arrives.

```python
# Conceptual test matrix (not implemented yet)
class DetectorContractTests(ABC):
    @pytest.fixture
    def detector(self) -> IDetector: ...

    def test_detect_returns_valid_bbox(self, detector, sample_frame): ...
    def test_health_reports_ready(self, detector): ...
    def test_unknown_frame_size_handled(self, detector): ...

class StubDetectorTests(DetectorContractTests): ...
# Later: class YoloDetectorTests(DetectorContractTests): ...
```

Same pattern for `ITracker`, `IFrameSource`.

### End-to-End Tests

**Stack:** `docker-compose.test.yml` — full services up.

| Scenario | Assertion |
|----------|-----------|
| Happy path | POST ingestion job → poll until completed → GET footfall > 0 |
| Stub pipeline | Known synthetic detection count → predictable footfall |
| WebSocket | Subscribe → receive `analytics.rollup.updated` within 5s |
| Failure | Invalid camera URI → job status `failed`, DLQ empty |
| Idempotency | Duplicate frame event → single detection row |

**Run frequency:** Nightly (slow); smoke subset on every PR.

## Test Data Strategy (No Real CCTV)

| Fixture | Source |
|---------|--------|
| Sample frames | Generated solid-color PNGs (1920×1080) in `tests/fixtures/frames/` |
| Sample video | FFmpeg-generated 10s clip (committed, <1MB) |
| Store/camera config | Factory functions (`polyfactory` or hand-rolled) |
| Zones | Normalized rectangles — no real store layout |

When dataset arrives:
- Add **optional** `tests/fixtures/real/` gitignored directory
- Separate `pytest -m real_dataset` marker — never required for CI

## Mocking Boundaries

| Mock | Allowed | Forbidden |
|------|---------|-----------|
| `IDetector` in analytics tests | Yes | — |
| PostgreSQL in unit tests | Yes (fake repo) | — |
| PostgreSQL in repository tests | No — use testcontainers | Mocking SQL |
| Redis in messaging tests | No — use testcontainers | In-memory fake for integration |
| Time | `freezegun` for bucket boundaries | — |

## CI Pipeline (Design)

```yaml
# .github/workflows/ci.yml (reference)
jobs:
  lint:
    - ruff check, ruff format --check, mypy
  unit:
    - pytest tests/unit -q
  integration:
    - docker compose -f docker-compose.test.yml up -d
    - alembic upgrade head
    - pytest tests/integration tests/contract -q
  e2e:
    - pytest tests/e2e -q --timeout=300
```

## Quality Gates

| Gate | Threshold |
|------|-----------|
| Unit test pass | 100% |
| Integration pass | 100% |
| OpenAPI contract | No breaking diff without major version bump |
| Event schema | All fixtures validate |
| Coverage (domain+application) | ≥ 90% |
| Coverage (overall) | ≥ 80% |

## Performance / Load Testing (Phase 2)

- **Locust** or **k6** against analytics query endpoints
- **Target:** 100 concurrent WebSocket clients, 1000 frames/min through stub pipeline
- GPU load test deferred until YOLO adapter exists

## Security Testing

- API key scope enforcement tests
- Tenant isolation: tenant A cannot read tenant B stores (integration)
- SQL injection: parameterized queries only (static analysis + schemathesis)

## Observability in Tests

Assert structured log output in integration tests for critical paths:

```python
caplog or structlog capture → assert correlation_id present
```

Metrics: scrape `/metrics` in e2e — assert `si_frames_processed_total` incremented.
