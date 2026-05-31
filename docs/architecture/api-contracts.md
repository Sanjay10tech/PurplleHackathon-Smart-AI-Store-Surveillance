# API Contract Specification

**Base URL:** `/api/v1`  
**Auth:** Bearer JWT or API key (`Authorization: Bearer <token>` / `X-API-Key: <key>`)  
**Content-Type:** `application/json`  
**Timestamps:** ISO 8601 UTC  
**IDs:** UUID v4  
**Pagination:** Cursor-based (`cursor`, `limit`); default `limit=50`, max `200`  
**Errors:** RFC 7807 Problem Details (`application/problem+json`)

## Standard Error Response

```json
{
  "type": "https://store-intelligence/errors/validation",
  "title": "Validation Error",
  "status": 422,
  "detail": "camera source_uri is required when source_type is rtsp",
  "instance": "/api/v1/cameras",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "errors": [
    { "field": "source_uri", "message": "required" }
  ]
}
```

## Common Headers

| Header | Direction | Purpose |
|--------|-----------|---------|
| `X-Correlation-ID` | Request/Response | Client-provided or server-generated trace ID |
| `X-Tenant-ID` | Request | Required for multi-tenant admin contexts |
| `Idempotency-Key` | Request | POST mutations (ingestion jobs, camera create) |

---

## Health & Meta

### `GET /health`

Liveness probe. No auth.

**Response 200:**
```json
{ "status": "ok", "service": "store-intelligence-api", "version": "0.1.0" }
```

### `GET /health/ready`

Readiness: DB + Redis connectivity.

**Response 200:**
```json
{
  "status": "ready",
  "checks": {
    "database": "up",
    "redis": "up",
    "object_storage": "up"
  }
}
```

**Response 503:** Any dependency down.

### `GET /openapi.json`

Auto-generated OpenAPI 3.1 spec (FastAPI).

---

## Stores

### `GET /stores`

List stores for authenticated tenant.

**Query:** `cursor`, `limit`, `search` (name)

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Downtown Flagship",
      "timezone": "America/New_York",
      "geo_location": { "lat": 40.7128, "lng": -74.0060 },
      "config": {},
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "next_cursor": "eyJ..."
}
```

### `POST /stores`

**Request:**
```json
{
  "name": "Downtown Flagship",
  "timezone": "America/New_York",
  "geo_location": { "lat": 40.7128, "lng": -74.0060 },
  "config": {}
}
```

**Response 201:** Store object.

### `GET /stores/{store_id}`

**Response 200:** Store object.

### `PATCH /stores/{store_id}`

Partial update. **Response 200:** Updated store.

### `DELETE /stores/{store_id}`

Soft delete. **Response 204.**

---

## Cameras

### `GET /stores/{store_id}/cameras`

**Query:** `status` (active|inactive|error), `cursor`, `limit`

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "store_id": "uuid",
      "name": "Entrance Cam 1",
      "source_type": "rtsp",
      "source_uri": "rtsp://...",
      "status": "active",
      "calibration": null,
      "config": { "target_fps": 5, "pipeline_profile": "default" },
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "next_cursor": null
}
```

### `POST /stores/{store_id}/cameras`

**Request:**
```json
{
  "name": "Entrance Cam 1",
  "source_type": "rtsp",
  "source_uri": "rtsp://nvr.local/stream1",
  "config": { "target_fps": 5 }
}
```

`source_type` enum: `rtsp`, `file`, `s3`, `webhook` (future).

**Response 201:** Camera object.

### `GET /cameras/{camera_id}`

**Response 200:** Camera object.

### `PATCH /cameras/{camera_id}`

**Response 200:** Updated camera.

### `POST /cameras/{camera_id}/calibration`

Upload or update calibration metadata (not the video itself).

**Request:**
```json
{
  "reference_resolution": [1920, 1080],
  "homography": [[1,0,0],[0,1,0],[0,0,1]],
  "notes": "Calibrated 2026-05-01"
}
```

**Response 200:** Camera object with updated `calibration`.

---

## Zones

### `GET /cameras/{camera_id}/zones`

**Response 200:**
```json
{
  "items": [
    {
      "id": "uuid",
      "camera_id": "uuid",
      "name": "Checkout Queue",
      "zone_type": "queue",
      "polygon": {
        "points": [[0.1, 0.2], [0.5, 0.2], [0.5, 0.8], [0.1, 0.8]],
        "coordinate_space": "normalized"
      },
      "config": {},
      "active": true
    }
  ]
}
```

### `POST /cameras/{camera_id}/zones`

**Request:**
```json
{
  "name": "Checkout Queue",
  "zone_type": "queue",
  "polygon": {
    "points": [[0.1, 0.2], [0.5, 0.2], [0.5, 0.8], [0.1, 0.8]],
    "coordinate_space": "normalized"
  },
  "config": {}
}
```

`zone_type` is a **string**, not a fixed enum — tenants define semantics.

**Response 201:** Zone object.

### `PATCH /zones/{zone_id}`

**Response 200:** Updated zone.

### `DELETE /zones/{zone_id}`

**Response 204.**

---

## Class Labels

Tenant-configurable mapping between model output and display names.

### `GET /class-labels`

**Response 200:** List of `{ id, external_id, display_name, category, metadata }`.

### `POST /class-labels`

**Request:**
```json
{
  "external_id": "0",
  "display_name": "Person",
  "category": "visitor",
  "metadata": { "count_in_footfall": true }
}
```

**Response 201.**

---

## Ingestion

### `POST /ingestion/jobs`

Start processing for a camera source. Supports idempotency key.

**Request:**
```json
{
  "camera_id": "uuid",
  "source_override": {
    "type": "file",
    "uri": "s3://bucket/path/video.mp4"
  },
  "frame_range": { "start": 0, "end": null },
  "pipeline_profile": "default"
}
```

**Response 202:**
```json
{
  "ingest_job_id": "uuid",
  "status": "pending",
  "correlation_id": "uuid"
}
```

### `GET /ingestion/jobs/{job_id}`

**Response 200:**
```json
{
  "id": "uuid",
  "camera_id": "uuid",
  "status": "processing",
  "frame_count": 1200,
  "processed_frames": 450,
  "pipeline_run_id": "uuid",
  "started_at": "...",
  "completed_at": null,
  "error_detail": null
}
```

### `POST /ingestion/jobs/{job_id}/cancel`

**Response 200:** `{ "status": "cancelled" }`

---

## Events (Audit / Debug)

Read-only access to persisted domain events.

### `GET /events`

**Query:** `aggregate_type`, `aggregate_id`, `event_type`, `from`, `to`, `cursor`, `limit`

**Response 200:**
```json
{
  "items": [
    {
      "event_id": "uuid",
      "event_type": "vision.frame.processed",
      "schema_version": "1.0.0",
      "occurred_at": "...",
      "aggregate": { "type": "pipeline_run", "id": "uuid" },
      "payload": { }
    }
  ],
  "next_cursor": "..."
}
```

---

## Analytics

### `GET /stores/{store_id}/analytics/footfall`

**Query:**
- `from`, `to` (required, ISO timestamps)
- `granularity`: `minute` | `hour` | `day` (default `hour`)
- `camera_id` (optional filter)
- `class_label_id` (optional)

**Response 200:**
```json
{
  "store_id": "uuid",
  "metric": "footfall.count",
  "granularity": "hour",
  "series": [
    { "bucket_start": "2026-05-30T12:00:00Z", "value": 142, "sample_count": 142 }
  ],
  "meta": { "partial": false }
}
```

### `GET /stores/{store_id}/analytics/dwell`

Zone dwell time statistics.

**Query:** `from`, `to`, `zone_id`, `stat`: `avg` | `p50` | `p95` | `max`

**Response 200:**
```json
{
  "zone_id": "uuid",
  "stat": "p50",
  "series": [
    { "bucket_start": "...", "value_ms": 45000 }
  ]
}
```

### `GET /stores/{store_id}/analytics/occupancy`

Current or historical zone occupancy.

**Query:** `zone_id`, `from`, `to` (omit `to` for latest snapshot)

**Response 200:**
```json
{
  "zone_id": "uuid",
  "current_count": 12,
  "as_of": "2026-05-30T12:00:00Z"
}
```

### `GET /stores/{store_id}/analytics/heatmap`

**Query:** `camera_id`, `from`, `to`, `grid_size` (default 32)

**Response 200:**
```json
{
  "camera_id": "uuid",
  "grid_size": 32,
  "cells": [
    { "x": 10, "y": 5, "count": 87 }
  ]
}
```

### `POST /stores/{store_id}/analytics/export`

Async export job (CSV/Parquet).

**Request:**
```json
{
  "metrics": ["footfall.count", "zone.dwell.p50"],
  "from": "2026-05-01T00:00:00Z",
  "to": "2026-05-30T00:00:00Z",
  "format": "csv"
}
```

**Response 202:**
```json
{ "export_job_id": "uuid", "status": "pending" }
```

### `GET /analytics/exports/{export_job_id}`

**Response 200:**
```json
{
  "id": "uuid",
  "status": "completed",
  "download_url": "https://...",
  "expires_at": "..."
}
```

---

## Real-time (WebSocket)

### `WS /ws/analytics/{store_id}`

**Auth:** Query param `token` or subprotocol header.

**Client → Server (subscribe):**
```json
{
  "action": "subscribe",
  "channels": ["footfall", "occupancy", "alerts"],
  "filters": { "camera_ids": ["uuid"], "zone_ids": ["uuid"] }
}
```

**Server → Client (update):**
```json
{
  "type": "analytics.rollup.updated",
  "store_id": "uuid",
  "metric_name": "footfall.count",
  "bucket_start": "2026-05-30T12:00:00Z",
  "value": 143,
  "as_of": "2026-05-30T12:05:00Z"
}
```

**Server → Client (heartbeat):**
```json
{ "type": "ping", "ts": "2026-05-30T12:00:00Z" }
```

---

## Pipeline Status (Observability)

### `GET /pipeline/status`

Admin endpoint: stub vs. real pipeline, model version.

**Response 200:**
```json
{
  "mode": "stub",
  "detector": { "name": "StubDetector", "version": "0.0.0" },
  "tracker": { "name": "StubTracker", "version": "0.0.0" },
  "ready": true
}
```

---

## Rate Limits

| Tier | REST | WebSocket |
|------|------|-----------|
| Default | 100 req/min per API key | 5 connections per store |
| Analytics heavy | 20 export jobs/day | — |

**Response 429:** Problem Details with `Retry-After` header.

## API Versioning Strategy

- URL prefix `/api/v1` — breaking changes → `/api/v2`.
- Deprecation: `Sunset` header + 6-month overlap.
- OpenAPI spec versioned in repo at `docs/openapi/v1.yaml` (exported from running app).
