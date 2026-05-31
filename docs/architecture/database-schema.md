# Database Schema

## Design Goals

- **Multi-tenant ready** — `tenant_id` on all tenant-scoped tables from day one.
- **No dataset lock-in** — Class labels, zone types, and camera metadata stored as configurable JSONB, not enum columns tied to a specific CCTV vendor.
- **Event audit trail** — Immutable append-only event log for replay and debugging.
- **Analytics-friendly** — Time-series friendly indexes; optional TimescaleDB hypertables for high-volume track points.
- **Soft deletes** — `deleted_at` on configuration entities; hard delete only for GDPR purge jobs.

## Entity-Relationship Diagram (Text)

```
┌─────────────────┐       ┌─────────────────┐
│     tenants     │       │      users      │
├─────────────────┤       ├─────────────────┤
│ PK id           │───┐   │ PK id           │
│    name         │   │   │ FK tenant_id    │──┐
│    slug         │   │   │    email        │  │
│    settings     │   │   │    role         │  │
│    created_at   │   │   │    created_at   │  │
└─────────────────┘   │   └─────────────────┘  │
         │            │            │           │
         │ 1:N        │            │           │
         ▼            │            ▼           │
┌─────────────────┐   │   ┌─────────────────┐  │
│     stores      │   │   │  api_keys       │  │
├─────────────────┤   │   ├─────────────────┤  │
│ PK id           │   └──►│ FK tenant_id    │◄─┘
│ FK tenant_id    │       │ FK user_id (opt)│
│    name         │       │    key_hash     │
│    timezone     │       │    scopes       │
│    geo_location │       │    expires_at   │
│    config       │       └─────────────────┘
│    created_at   │
└────────┬────────┘
         │ 1:N
         ▼
┌─────────────────┐       ┌─────────────────┐
│    cameras      │       │  camera_zones   │
├─────────────────┤       ├─────────────────┤
│ PK id           │───┐   │ PK id           │
│ FK store_id     │   │   │ FK camera_id    │◄──┐
│    name         │   └──►│    name         │   │
│    source_type  │       │    zone_type    │   │
│    source_uri   │       │    polygon      │   │
│    status       │       │    config       │   │
│    calibration  │       │    active       │   │
│    config       │       └─────────────────┘   │
│    created_at   │                              │
└────────┬────────┘                              │
         │                                       │
         │ 1:N                                   │
         ▼                                       │
┌─────────────────┐       ┌─────────────────┐   │
│  media_assets   │       │  ingest_jobs    │   │
├─────────────────┤       ├─────────────────┤   │
│ PK id           │◄──────│ FK camera_id    │   │
│ FK camera_id    │       │ FK media_asset  │   │
│    asset_type   │       │    status       │   │
│    storage_key  │       │    frame_count  │   │
│    mime_type    │       │    started_at   │   │
│    duration_ms  │       │    completed_at │   │
│    metadata     │       │    error_detail │   │
│    created_at   │       └─────────────────┘   │
└─────────────────┘                              │
                                                 │
┌─────────────────┐       ┌─────────────────┐   │
│  class_labels   │       │ pipeline_runs   │   │
├─────────────────┤       ├─────────────────┤   │
│ PK id           │       │ PK id           │   │
│ FK tenant_id    │       │ FK ingest_job   │   │
│    external_id  │       │    pipeline_mode│   │
│    display_name │       │    model_version│   │
│    category     │       │    status       │   │
│    metadata     │       │    metrics      │   │
└─────────────────┘       └────────┬────────┘   │
                                   │ 1:N         │
                                   ▼             │
                          ┌─────────────────┐   │
                          │    tracks       │   │
                          ├─────────────────┤   │
                          │ PK id           │   │
                          │ FK pipeline_run │   │
                          │ FK camera_id    │   │
                          │    track_id_ext │   │  ← ByteTrack local ID
                          │    first_seen   │   │
                          │    last_seen    │   │
                          │    metadata     │   │
                          └────────┬────────┘   │
                                   │ 1:N         │
                    ┌──────────────┼──────────────┘
                    ▼              ▼
           ┌──────────────┐  ┌─────────────────┐
           │ detections   │  │  zone_visits    │
           ├──────────────┤  ├─────────────────┤
           │ PK id        │  │ PK id           │
           │ FK track_id  │  │ FK track_id     │
           │ FK class_lbl │  │ FK zone_id      │
           │    frame_ts  │  │    entered_at   │
           │    bbox      │  │    exited_at    │
           │    confidence│  │    dwell_ms     │
           │    frame_ref │  └─────────────────┘
           └──────────────┘

┌─────────────────────────────────────────────────────────┐
│                    domain_events                         │
│              (append-only event store)                   │
├─────────────────────────────────────────────────────────┤
│ PK id (UUID)                                            │
│    tenant_id, aggregate_type, aggregate_id              │
│    event_type, schema_version, payload (JSONB)          │
│    correlation_id, causation_id                         │
│    occurred_at, recorded_at                             │
│    idempotency_key (UNIQUE, nullable)                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────┐       ┌─────────────────────────┐
│ analytics_      │       │ analytics_snapshots     │
│ rollups         │       ├─────────────────────────┤
├─────────────────┤       │ PK id                   │
│ PK id           │       │ FK store_id             │
│ FK store_id     │       │    snapshot_type        │
│ FK camera_id    │       │    period_start/end     │
│    metric_name  │       │    payload (JSONB)      │
│    bucket_start │       │    created_at           │
│    bucket_end   │       └─────────────────────────┘
│    dimensions   │
│    value        │
│    sample_count │
└─────────────────┘
```

## Table Specifications

### Core Configuration

| Table | Primary Purpose | Key Columns |
|-------|-----------------|-------------|
| `tenants` | SaaS isolation | `slug`, `settings` JSONB |
| `stores` | Physical retail location | `timezone`, `geo_location`, `config` |
| `cameras` | Video source registry | `source_type` (rtsp/file/s3), `source_uri`, `calibration` JSONB |
| `camera_zones` | Region-of-interest polygons | `polygon` JSONB array of `[x,y]`, `zone_type` string |
| `class_labels` | Tenant-defined detection classes | `external_id` (model class index/name), `display_name` |

### Processing Pipeline

| Table | Primary Purpose | Key Columns |
|-------|-----------------|-------------|
| `media_assets` | Stored frame/video references | `storage_key`, `metadata` JSONB |
| `ingest_jobs` | Batch/stream ingestion unit | `status` enum: pending/processing/completed/failed |
| `pipeline_runs` | One detection pass over a job | `pipeline_mode`, `model_version`, `metrics` JSONB |
| `tracks` | Persistent track identity | `track_id_ext` (tracker-local), time bounds |
| `detections` | Per-frame observations | `bbox` JSONB `{x,y,w,h}`, `confidence`, `frame_ts` |
| `zone_visits` | Derived zone analytics | `dwell_ms`, enter/exit timestamps |

### Event Store & Analytics

| Table | Primary Purpose | Key Columns |
|-------|-----------------|-------------|
| `domain_events` | Immutable event log | `event_type`, `schema_version`, `payload`, correlation fields |
| `analytics_rollups` | Pre-aggregated metrics | `metric_name`, time bucket, `dimensions` JSONB |
| `analytics_snapshots` | Point-in-time reports | `snapshot_type`, period bounds |

## Index Strategy

```sql
-- Tenant-scoped lookups
CREATE INDEX idx_stores_tenant ON stores(tenant_id);
CREATE INDEX idx_cameras_store ON cameras(store_id) WHERE deleted_at IS NULL;

-- Time-series queries (detections, events)
CREATE INDEX idx_detections_frame_ts ON detections(camera_id, frame_ts DESC);
CREATE INDEX idx_domain_events_occurred ON domain_events(tenant_id, occurred_at DESC);
CREATE INDEX idx_domain_events_aggregate ON domain_events(aggregate_type, aggregate_id, occurred_at);

-- Analytics rollups
CREATE UNIQUE INDEX idx_rollups_unique ON analytics_rollups(
  store_id, camera_id, metric_name, bucket_start, dimensions
);

-- Idempotency
CREATE UNIQUE INDEX idx_events_idempotency ON domain_events(idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

## JSONB Schema Conventions (Not Enforced at DB Level)

Documented in application layer; validated via Pydantic:

| Field | Example Shape |
|-------|---------------|
| `cameras.calibration` | `{ "homography": [[...]], "reference_resolution": [1920,1080] }` |
| `cameras.config` | `{ "target_fps": 5, "roi_crop": null, "pipeline_profile": "default" }` |
| `camera_zones.polygon` | `{ "points": [[0.1,0.2], ...], "coordinate_space": "normalized" }` |
| `detections.bbox` | `{ "x": 0.5, "y": 0.3, "w": 0.1, "h": 0.2, "space": "normalized" }` |

**Tradeoff:** JSONB flexibility vs. query performance. Hot paths (footfall counts) use `analytics_rollups`; raw detections queried only for drill-down.

## Migration Strategy

- Alembic sequential migrations; never edit applied migrations.
- Backward-compatible column adds only in minor releases.
- Event payload versioning handled in application layer, not DB schema per event type.

## Optional Extension: TimescaleDB

When detection volume exceeds ~10M rows/month:

- Convert `detections` and `domain_events` to hypertables partitioned on `occurred_at` / `frame_ts`.
- Enable compression policies for data older than 30 days.
- Keep rollups in standard PostgreSQL tables for fast dashboard queries.
