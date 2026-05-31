# BI Validation Report — Purplle Pilot Store

Generated from integration tests in `tests/scenarios/test_bi_full_validation.py` using pipeline-shaped event data (`tests/helpers/pipeline_event_seed.py`).

**Store ID:** `00000000-0000-0000-0000-000000000101`  
**Validation date:** 2026-05-30  
**Method:** Golden retail day seed → query all BI endpoints → assert against expected KPIs

---

## Executive summary

The business intelligence layer was validated end-to-end against events emitted by the detection pipeline. All five analytics endpoints (`/metrics`, `/funnel`, `/heatmap`, `/anomalies`, `/health`) return consistent results. Staff tracks are excluded from customer metrics at both the pipeline emit layer and the BI query layer.

| Check | Result |
|-------|--------|
| Event ingestion (batch) | Pass — 202 accepted, idempotent on replay |
| Staff exclusion | Pass — `class_label: staff` and `staff_only` zones filtered |
| Re-entry dedupe | Pass — `re_entry_count` increments, stage `count` unchanged |
| Empty store | Pass — stable empty metadata, STALE_FEED raised |
| Zero purchase | Pass — PURCHASE count 0, 100% drop-off at billing |
| Full pipeline chain | Pass — video → detect → ingest → BI |

---

## Golden retail day scenario

Synthetic data mirrors `pipeline/emit.py` payloads: `vision.zone.entered`, `vision.frame.processed`, and `analytics.purchase.completed` with `session_id`, `external_track_id`, `zone_type`, and `class_label`.

| Parameter | Value |
|-----------|-------|
| Unique visitors (sessions) | **10** |
| Purchases | **3** |
| Conversion rate (ENTRY → PURCHASE) | **30%** (0.3) |
| Browse re-entry visitors | **1** (re_entry_count ≥ 1 on ZONE_VISIT) |
| Staff events ingested | **1** (excluded from funnel/heatmap/anomaly queue counts) |

---

## Funnel stages

Expected first-touch counts for the golden day (dedupe by `external_track_id`, default on):

| Stage | Count | Notes |
|-------|------:|-------|
| ENTRY | 10 | One per visitor session |
| ZONE_VISIT | 10 | Browse zone entered |
| BILLING_QUEUE | 10 | Per-visitor queue + spike events in heatmap/anomaly |
| PURCHASE | 3 | Matches transaction + purchase events |

**Re-entry:** Visitor 0 enters browse twice. Funnel reports `ZONE_VISIT.count = 1`, `ZONE_VISIT.re_entry_count = 1` — visitors are not double-counted.

**Zero purchase scenario** (separate test): visitor reaches `checkout` but PURCHASE remains **0** with `drop_off_rate = 1.0` at BILLING_QUEUE.

---

## Metrics (`GET /stores/{id}/metrics`)

| Source | When |
|--------|------|
| `store_metrics` | Pre-aggregated buckets exist (golden day seeds `footfall.count = 10`) |
| `placeholder` | No buckets — reports vision event count or “awaiting CCTV” message |

Golden day response:

- `meta.source`: **store_metrics**
- `series[0].value`: **10.0** (hourly footfall bucket)
- `meta.partial`: **false**

After live pipeline ingest (no metric projector):

- `meta.source`: **placeholder**
- `meta.message`: **“N vision events recorded; metric projection pending.”**

---

## Heatmap (`GET /stores/{id}/heatmap`)

| Metric | Golden day |
|--------|------------|
| Total zone visits | ≥ 10 (visitor journeys + queue spike events) |
| Queue zone visits | ≥ 38 (10 visitor queue enters + 28 spike events) |
| Staff zones | **0** (staff_only event excluded) |
| Data confidence | MEDIUM or HIGH on active zones |

Heatmap counts **every** `vision.zone.entered` (including re-entries). Funnel uses first-touch — this asymmetry is by design.

---

## Anomalies (`GET /stores/{id}/anomalies`)

Golden day seeds baseline queue traffic (8 visits) vs current window spike (28 visits):

| Anomaly | Detected | Severity |
|---------|----------|----------|
| **QUEUE_SPIKE** | Yes | WARN or CRITICAL |
| spike_ratio | ≥ **1.5** | vs baseline |
| STALE_FEED | No | Recent `vision.frame.processed` present |
| CONVERSION_DROP | No | Not seeded in golden day |
| DEAD_ZONE | No | All zones have traffic |

**Queue depth (proxy):** peak billing_queue visit count in the current 24 h window = **28** spike events (+ per-visitor queue enters).

---

## Health (`GET /health`)

After ingesting vision events:

| Check | Value |
|-------|-------|
| `status` | **ok** |
| `checks.database` | **up** |
| `checks.feed` | **fresh** |
| `stale_feed` | **false** |
| `last_event_at` | Within 15 minutes |

Empty store (no events): `feed=unknown`, `stale_feed=true`, status **degraded**.

---

## Idempotent ingestion

Re-posting the same event batch returns HTTP **202** with:

- `summary.duplicate` = batch size
- `summary.accepted` = 0

Verified in `test_duplicate_batch_ingest_is_idempotent`.

---

## Full pipeline integration

```
Video (synthetic frames)
  → TrajectoryMockPersonDetector
  → ByteTrack + zone lines (CAM 3 entry)
  → EventBuilder (vision.* events)
  → POST /api/v1/events/ingest (batch)
  → Sessions persisted to DB
  → /metrics (placeholder + event count)
  → /funnel (ENTRY ≥ 1)
  → /heatmap (zones ≥ 1)
  → /anomalies (no STALE_FEED after ingest)
  → /health (feed fresh)
```

Test: `tests/scenarios/test_bi_full_validation.py::test_full_pipeline_to_anomalies_chain`

---

## Test coverage map

| Requirement | Test module |
|-------------|-------------|
| Empty store | `test_bi_full_validation`, `test_empty_store` |
| Zero purchase | `test_bi_full_validation`, `test_zero_purchases` |
| Re-entry | `test_bi_full_validation`, `test_reentry` |
| Staff exclusion | `test_bi_full_validation` |
| Duplicate ingest | `test_bi_full_validation`, `test_duplicate_ingestion` |
| Queue spike | `test_bi_full_validation` (golden day), `test_queue_spike` |
| All stage events | `test_all_stage_events` |
| Pipeline E2E | `test_pipeline_e2e`, `test_bi_full_validation` |
| Analytics service | `tests/test_analytics_service.py` |

Run validation suite:

```bash
pytest tests/scenarios/test_bi_full_validation.py tests/test_analytics_service.py -v
```

---

## Known limitations (unchanged architecture)

1. **Metrics projection worker** not deployed — live pipeline populates `events` only; `store_metrics` requires explicit seed or future projector.
2. **Heatmap vs funnel re-entry** — heatmap counts all enters; funnel first-touch only.
3. **Staff exclusion** — primary gate at `pipeline/emit.py`; BI layer adds `class_label` / `staff_only` filter as defense in depth.
