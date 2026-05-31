# Staff vs Customer Classification Report

**Date:** 2026-05-30  
**Scope:** Reduce staff contamination in customer BI metrics (funnel, heatmap, footfall).

## Problem

Staff at billing counters, consultation desks, and stock areas were often classified as `visitor` until very late (or never), polluting:

- Zone enter events (`billing_queue`, `aisle`, `consultation`)
- Visitor sessions and funnel ENTRY counts
- Cross-camera Re-ID (staff embeddings linked to visitor global IDs)

Legacy logic only used:

1. Backroom camera → always staff
2. Full-bbox dark uniform over 60 frames (~12 s @ 5 FPS)
3. Dwell in `staff_only` polygons ≥ 300 s

Staff classification ran **before** zone analysis, so polygon dwell was one frame stale.

## Improvements

### 1. Uniform patterns

- Dark-pixel ratio measured on **upper torso** (top 60% of bbox) — matches black/grey polo aprons
- **Billing camera** uses faster threshold: 30 frames vs 60 on floor cameras

### 2. Long duration presence

| Signal | Threshold | Cameras |
|--------|-----------|---------|
| Billing camera total presence | 180 s | billing |
| Billing zone dwell (`billing_queue`, `checkout`) | 120 s | any |
| Consultation zone dwell | 600 s | any |
| Staff-only zone dwell | 300 s | any |
| Any-camera track duration | 900 s | any |

### 3. Repeated movement patterns

- **Shuttle detection:** ≥ 3 alternations between zone-type pairs (e.g. `consultation ↔ aisle`, `billing_queue ↔ aisle`)
- **Counter loiter:** high path length with low net displacement (ratio ≥ 4.0 over ≥ 30 frames)

### 4. Pipeline integration

- Zone analysis runs **before** staff classification (accurate dwell)
- On staff promotion: `GlobalIdentityRegistry.mark_role(staff)`, session ended with `metadata.staff=true`, `session_id` cleared
- Staff tracks no longer emit customer zone events (existing `emit.py` rule)

### 5. BI defense in depth

- `is_customer_session()` excludes staff sessions from funnel ENTRY snapshots
- `project_demo_metrics.py` filters staff zone events for footfall projection
- Heatmap already uses `is_customer_metric_event()`

## Before / After (scenario simulation)

Run: `python scripts/analyze_staff_classification.py`

| Scenario | Legacy staff | Improved staff |
|----------|--------------|----------------|
| Billing counter dark uniform (30 frames) | No | **Yes** |
| Billing long presence (200 s) | No | **Yes** |
| Consultation ↔ aisle shuttle | No | **Yes** |
| Counter loiter (pacing) | No | **Yes** |
| Brief customer visit (45 s) | No | No |
| Staff-only dwell (310 s) | **Yes** | **Yes** |

**Contamination:** legacy misclassified 4/5 staff-like scenarios as visitors; improved detects 5/5 staff scenarios with 0 false staff on the brief customer visit.

## Configuration

See `pipeline/config.yaml` → `staff:` for all thresholds. Key overrides:

```yaml
uniform_frames_required_billing: 30
billing_presence_seconds: 180
billing_zone_dwell_seconds: 120
consultation_dwell_seconds: 600
shuttle_min_cycles: 3
loiter_path_ratio: 4.0
```

## Tests

- `tests/test_pipeline.py` → `TestStaffClassifier`
- `tests/unit/test_vision_filters.py` → session filter
- `tests/scenarios/test_bi_full_validation.py` → staff heatmap exclusion (existing)

## Recommendations

1. **CAM 5 billing:** expect most counter tracks to classify within 2–3 min via billing presence + zone dwell
2. **Tune shuttle pairs** per store layout if staff routes differ (e.g. `checkout ↔ stock`)
3. **Optional:** add HSV black/grey cluster detection for non-uniform staff apparel in future iteration
4. **Validate on real footage:** run mock/real pipeline ingest and compare funnel `unique_visitors` before/after on a known staff-heavy hour
