# Logging Strategy

## Goals

1. **Debug async pipelines** — correlate logs across API → workers via `correlation_id`.
2. **Support production ops** — structured JSON, machine-parseable, no PII in logs by default.
3. **Enable SLI/SLO tracking** — log fields align with Prometheus metrics where possible.
4. **Safe before dataset** — no raw frame bytes or video paths with sensitive info in logs unless debug flag enabled.

## Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Library | `structlog` + stdlib `logging` | Structured context, processor chain |
| Format (prod) | JSON to stdout | Container log aggregation (Loki/CloudWatch) |
| Format (dev) | Colored console renderer | Human readability |
| Tracing | OpenTelemetry (optional profile) | Distributed traces complement logs |
| Metrics | Prometheus client | Counters/histograms for pipeline SLIs |

## Log Levels by Component

| Component | Default | Debug Adds |
|-----------|---------|------------|
| API routes | INFO | Request/response bodies (sanitized) |
| Use cases | INFO | Business decision points |
| Workers | INFO | Per-job lifecycle |
| Detection pipeline | WARNING | Per-frame detect counts (not bboxes) |
| Infrastructure | WARNING | Connection retries |
| SQLAlchemy | WARNING | Query text only in DEBUG |

## Structured Log Schema

Every log entry includes:

```json
{
  "timestamp": "2026-05-30T12:00:00.000Z",
  "level": "info",
  "logger": "store_intelligence.workers.detection",
  "message": "frame_processed",
  "correlation_id": "uuid",
  "tenant_id": "uuid",
  "service": "worker-detection",
  "environment": "production",
  "event": {
    "ingest_job_id": "uuid",
    "frame_index": 42,
    "processing_ms": 45,
    "detection_count": 3,
    "track_count": 2
  }
}
```

### Standard Context Fields

| Field | Source | Always Present |
|-------|--------|----------------|
| `correlation_id` | HTTP header or generated | Yes |
| `tenant_id` | Auth / event envelope | When known |
| `service` | Env `SERVICE_NAME` | Yes |
| `environment` | Env `ENVIRONMENT` | Yes |
| `trace_id` | OpenTelemetry | When tracing enabled |

### Pipeline-Specific Fields (Never Log by Default)

- Raw bounding box coordinates (use counts only)
- Frame binary / base64
- Full RTSP URLs with credentials (redact userinfo)
- Person-identifiable attributes

## Redaction Rules

```
RTSP URL: rtsp://user:pass@host → rtsp://***:***@host
API keys: sk-live-abc123 → sk-live-***
Storage keys: log bucket + truncated key hash only
```

Implement via structlog processor `redact_sensitive_fields`.

## Key Log Events (Catalog)

| Event Name | Level | When |
|------------|-------|------|
| `http_request_completed` | INFO | Every API request (method, path, status, duration_ms) |
| `ingest_job_started` | INFO | Job picked up by worker |
| `ingest_job_completed` | INFO | Terminal success |
| `ingest_job_failed` | ERROR | Terminal failure with error_type |
| `frame_processed` | INFO | Detection worker finished frame |
| `pipeline_stub_mode` | WARNING | Startup when PIPELINE_MODE=stub |
| `event_publish_failed` | ERROR | Bus write failure |
| `event_handler_failed` | ERROR | Handler exception (before DLQ) |
| `dlq_message_received` | ERROR | Ops attention |
| `analytics_rollup_updated` | DEBUG | High volume — debug only |
| `websocket_client_subscribed` | INFO | Real-time channel |

## Correlation ID Lifecycle

```mermaid
flowchart LR
    A[Client or API generates UUID] --> B[ContextVar binding]
    B --> C[HTTP response header]
    B --> D[Event envelope]
    D --> E[Worker ContextVar from envelope]
    E --> F[All logs in handler]
    E --> G[domain_events row]
```

Middleware: `api/middleware/correlation.py` binds `correlation_id` to structlog contextvars on every request.

Workers: bind from consumed event envelope at handler entry; clear in `finally`.

## Request Logging (API)

Log once per request (not duplicate access + app logs):

```
method, path_template, status_code, duration_ms, client_ip (hashed), user_id, tenant_id
```

Exclude: `/health`, `/metrics` from verbose logging (DEBUG only).

## Error Logging

- **Expected errors** (404, 422): INFO/WARNING, no stack trace.
- **Unexpected errors** (500): ERROR with stack trace (`exc_info=True`).
- **Worker handler failures**: ERROR with `event_type`, `event_id`, retry count; stack trace.

## Log Aggregation Architecture

```
Container stdout (JSON)
  → Docker logging driver
  → Loki / Elasticsearch / CloudWatch
  → Grafana dashboards
```

Recommended Grafana panels:
- Ingest jobs/min by status
- Frame processing p95 latency
- DLQ depth
- Error rate by service

## Metrics vs. Logs Boundary

| Signal | Use For |
|--------|---------|
| **Metrics** | SLIs, alerting, dashboards (rates, histograms) |
| **Logs** | Debugging specific correlation_id, audit trail |
| **Traces** | Latency breakdown across detect → analytics |

Example metric: `si_frames_processed_total{camera_id, pipeline_mode}`  
Matching log: `frame_processed` at INFO for sampled debugging (1% sample in prod).

## Configuration

```yaml
# config/logging.yaml (reference)
version: 1
formatters:
  json:
    class: structlog.stdlib.ProcessorFormatter
handlers:
  console:
    class: logging.StreamHandler
    formatter: json
loggers:
  store_intelligence:
    level: INFO
  sqlalchemy.engine:
    level: WARNING
```

Environment overrides:
- `LOG_LEVEL=DEBUG`
- `LOG_SAMPLE_RATE=0.01` (high-volume events)
- `LOG_INCLUDE_bbox=false`

## Retention

| Environment | Retention |
|-------------|-----------|
| Development | 7 days local |
| Staging | 30 days |
| Production | 90 days hot, 1 year archive |

PII scrubbing job on archive tier if GDPR applies.
