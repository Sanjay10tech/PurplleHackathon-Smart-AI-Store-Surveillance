# Zone Mapping Strategy — Purplle Pilot Store

Proposed calibration plan for the five-camera dataset, aligned with the existing event contract (`vision.zone.entered`, `vision.zone.exited`) and funnel defaults in `app/domain/funnel/stages.py`. **No API or payload changes.**

---

## Design principles

1. **Normalized polygons** — All vertices in `[0, 1]` relative to frame width/height (architecture ADR: resolution-agnostic zones).
2. **String `zone_type`** — Tenant-defined semantics; map to funnel stages via `store.config.funnel.zone_type_mapping`.
3. **Lines for counting, polygons for dwell** — Entry/exit footfall uses directed line crossing; browse/queue uses polygon enter/exit with dwell derived from timestamps.
4. **One logical zone_id per semantic region** — Same physical queue referenced once on CAM 5; do not duplicate IDs on overlapping cameras unless implementing cross-camera fusion (phase 2).
5. **Camera role drives priority** — CAM 3 owns **ENTRY**; CAM 5 owns **BILLING_QUEUE**; CAM 1/2 own **ZONE_VISIT**.

---

## Default funnel mapping (existing code)

From `DEFAULT_ZONE_TYPE_MAPPING`:

| zone_type (proposed) | Funnel stage |
|----------------------|--------------|
| `entry`, `entrance` | ENTRY |
| `browse`, `aisle`, `display`, `zone` | ZONE_VISIT |
| `billing_queue`, `checkout`, `queue`, `billing` | BILLING_QUEUE |

Recommended `store.config` overlay for this store:

```json
{
  "funnel": {
    "zone_type_mapping": {
      "entry_threshold": "ENTRY",
      "entrance": "ENTRY",
      "browse_skincare": "ZONE_VISIT",
      "browse_cosmetics": "ZONE_VISIT",
      "promo_island": "ZONE_VISIT",
      "consultation": "ZONE_VISIT",
      "billing_queue": "BILLING_QUEUE",
      "checkout_active": "BILLING_QUEUE",
      "staff_only": "ZONE_VISIT"
    },
    "dedupe_by_track": true,
    "reentry_cooldown_minutes": 30
  },
  "anomaly": {
    "queue_spike_threshold_pct": 150,
    "conversion_drop_threshold_pct": 25,
    "dead_zone_minutes": 60
  }
}
```

`staff_only` maps to ZONE_VISIT for heatmap exclusion filters, not funnel advancement — filter in analytics queries by zone name prefix or `zone.config.exclude_from_funnel: true`.

---

## Camera-by-camera zone catalog

### CAM 3 — Entry / exit

| Zone name | zone_type | Geometry | Purpose |
|-----------|-----------|----------|---------|
| `entry_threshold` | `entry_threshold` | **Line:** (0.42, 0.33) → (0.68, 0.48) | Store entry/exit counting |
| `entry_landing` | `entrance` | **Polygon:** (0.05, 0.25, 0.55, 0.25, 0.55, 0.55, 0.05, 0.55) | Post-door landing / decompression |
| `occlusion_mask` | `ignore` | **Polygon:** (0.78, 0.0, 1.0, 0.0, 1.0, 1.0, 0.78, 1.0) | Right-side blind spot — suppress detections |

**Line crossing logic (detection worker / `IZoneAnalyzer`):**

- Compute track centroid per frame.
- **Entry event:** centroid crosses from exterior half-plane (dark floor, lower y in image) to interior.
- **Exit event:** reverse crossing within 30 s of last entry OR any outbound crossing.
- Emit `vision.zone.entered` with `zone_type: "entry_threshold"`, `payload.direction: "in"|"out"`.

**Confidence:** High for ENTRY stage — single source of truth for footfall.

---

### CAM 1 — Main floor (skincare)

| Zone name | zone_type | Normalized polygon (x,y pairs) | Notes |
|-----------|-----------|----------------------------------|-------|
| `browse_farmstay` | `browse_skincare` | (0.02,0.08)(0.18,0.08)(0.18,0.35)(0.02,0.35) | Left wall |
| `browse_face_shop` | `browse_skincare` | (0.18,0.08)(0.34,0.08)(0.34,0.35)(0.18,0.35) | |
| `browse_good_vibes` | `browse_skincare` | (0.34,0.08)(0.50,0.08)(0.50,0.35)(0.34,0.35) | |
| `browse_derma_co` | `browse_skincare` | (0.50,0.08)(0.66,0.08)(0.66,0.35)(0.50,0.35) | |
| `browse_minimalist` | `browse_skincare` | (0.66,0.08)(0.82,0.08)(0.82,0.35)(0.66,0.35) | |
| `browse_aqualogica` | `browse_skincare` | (0.82,0.08)(0.98,0.08)(0.98,0.35)(0.82,0.35) | |
| `promo_beat_the_heat` | `promo_island` | (0.35,0.62)(0.55,0.62)(0.55,0.88)(0.35,0.88) | Central island |
| `consultation_desk` | `consultation` | (0.72,0.55)(0.95,0.55)(0.95,0.85)(0.72,0.85) | Service, not POS |
| `aisle_circulation` | `aisle` | (0.05,0.40)(0.95,0.40)(0.95,0.95)(0.05,0.95) | Walk path — dwell low |

**Proposed entry/exit lines (aisle-level, not store entry):**

- **Line A:** y = 0.90, x ∈ [0.05, 0.95] — foreground circulation ingress
- **Line B:** x = 0.05, y ∈ [0.35, 0.95] — exit toward store core / checkout

Use for heatmap path density, not funnel ENTRY.

---

### CAM 2 — Main floor (cosmetics)

| Zone name | zone_type | Normalized polygon | Notes |
|-----------|-----------|-------------------|-------|
| `browse_maybelline` | `browse_cosmetics` | (0.72,0.05)(0.98,0.05)(0.98,0.32)(0.72,0.32) | |
| `browse_faces_canada` | `browse_cosmetics` | (0.58,0.05)(0.72,0.05)(0.72,0.32)(0.58,0.32) | |
| `browse_lakme` | `browse_cosmetics` | (0.44,0.05)(0.58,0.05)(0.58,0.32)(0.44,0.32) | High engagement in footage |
| `browse_swiss_beauty` | `browse_cosmetics` | (0.30,0.05)(0.44,0.05)(0.44,0.32)(0.30,0.32) | |
| `browse_mars` | `browse_cosmetics` | (0.18,0.05)(0.30,0.05)(0.30,0.32)(0.18,0.32) | |
| `browse_alps_loreal` | `browse_cosmetics` | (0.02,0.05)(0.18,0.05)(0.18,0.32)(0.02,0.32) | |
| `consultation_makeup` | `consultation` | (0.06,0.45)(0.28,0.45)(0.28,0.75)(0.06,0.75) | Service queue candidate |
| `promo_summer_essentials` | `promo_island` | (0.38,0.68)(0.58,0.68)(0.58,0.92)(0.38,0.92) | |
| `aisle_circulation` | `aisle` | (0.05,0.35)(0.95,0.35)(0.95,0.95)(0.05,0.95) | |

**Proposed lines:**

- **Line (left mouth):** x = 0.10, y ∈ [0.30, 0.80] — ingress from entrance / adjacent aisle
- **Line (checkout bound):** y = 0.92, x ∈ [0.20, 0.80] — exit toward billing (weak signal; prefer CAM 5 for queue)

---

### CAM 5 — Billing area

| Zone name | zone_type | Normalized polygon | Purpose |
|-----------|-----------|-------------------|---------|
| `billing_queue` | `billing_queue` | (0.05,0.45)(0.35,0.45)(0.35,0.88)(0.05,0.88) | Queue wait — **primary BILLING_QUEUE signal** |
| `checkout_active` | `checkout` | (0.30,0.35)(0.62,0.35)(0.62,0.65)(0.30,0.65) | At counter — service in progress |
| `checkout_staff` | `staff_only` | (0.28,0.30)(0.65,0.30)(0.65,0.55)(0.28,0.55) | Behind counter — exclude from queue depth |
| `backroom_mouth` | `staff_only` | (0.38,0.02)(0.58,0.02)(0.58,0.22)(0.38,0.22) | Links to CAM 4 |
| `accessories_impulse` | `display` | (0.72,0.15)(0.98,0.15)(0.98,0.95)(0.72,0.95) | Accessory upsell wall |

**Proposed lines:**

| Line | Coords | Event |
|------|--------|-------|
| Queue entry | x = 0.20, y ∈ [0.45, 0.88] | `billing_queue` entered |
| Queue to counter | x = 0.35, y ∈ [0.40, 0.70] | Advance to `checkout_active` |
| Checkout complete | y = 0.58, x ∈ [0.30, 0.65] | Exit billing (optional) |

**Queue depth metric:** count tracks in `billing_queue` excluding `checkout_staff` classified IDs.

---

### CAM 4 — Backroom (staff)

| Zone name | zone_type | Normalized polygon | Purpose |
|-----------|-----------|-------------------|---------|
| `stock_floor` | `staff_only` | (0.05,0.15)(0.95,0.15)(0.95,0.95)(0.05,0.95) | Full room |
| `door_to_sales` | `staff_only` | (0.35,0.02)(0.55,0.02)(0.55,0.12)(0.35,0.12) | Door line — staff in/out |

Exclude all zones from customer funnel and footfall; use for staff hour estimation and `STALE_FEED` secondary probe.

---

## Cross-camera zone fusion (phase 2)

Do **not** merge zones in phase 1 — emit per-camera events with distinct `zone_id`.

| Handoff | From | To | Method |
|---------|------|-----|--------|
| Enter store | CAM 3 `entry_threshold` | CAM 1/2 browse | Re-ID within 120 s (see `reid_strategy.md`) |
| Approach checkout | CAM 1/2 `aisle_circulation` exit | CAM 5 `billing_queue` enter | Re-ID within 180 s |
| Staff stock run | CAM 5 `backroom_mouth` | CAM 4 `door_to_sales` | Same `external_track_id` + staff classifier |

Session stitching in funnel calculator already dedupes by `external_track_id` when `dedupe_by_track: true`.

---

## Event emission contract (unchanged)

Each zone transition produces:

```json
{
  "event_type": "vision.zone.entered",
  "schema_version": "1.0.0",
  "payload": {
    "zone_id": "uuid-from-camera_zones-table",
    "zone_type": "billing_queue",
    "external_track_id": "bytetrack-42",
    "camera_id": "uuid",
    "centroid_norm": { "x": 0.21, "y": 0.67 },
    "confidence": 0.91
  }
}
```

Dwell is computed on exit:

```json
{
  "event_type": "vision.zone.exited",
  "payload": {
    "zone_id": "uuid",
    "zone_type": "browse_skincare",
    "external_track_id": "bytetrack-42",
    "dwell_ms": 45000
  }
}
```

Heatmap and funnel services consume these shapes today — no changes required.

---

## Calibration workflow

1. **Pilot frame export** — First ingestion job per camera at native 1920×1080.
2. **UI / JSON calibration** — `POST /cameras/{id}/calibration` with polygon vertices (architecture endpoint); store in `camera_zones.polygon`.
3. **Validate with clip replay** — Run detection worker on full 2.5 min clip; expect:
   - CAM 3: 0–3 entry events (matches low traffic clip)
   - CAM 2: highest browse zone visit count
   - CAM 5: queue events only when customer enters left floor polygon (not staff behind counter)
4. **Tune buffers** — Expand polygons 5% outward if missed entries at zone edges (common at high angle).
5. **Peak revalidation** — Repeat with weekday daytime footage before setting anomaly baselines.

---

## Heatmap integration

Current heatmap is **zone-based** (visits + dwell per `zone_id`). Proposed aggregation groups:

| Heatmap group | Member zones |
|---------------|--------------|
| Skincare | CAM 1 `browse_*` |
| Cosmetics | CAM 2 `browse_*` |
| Promo | `promo_*` on CAM 1/2 |
| Consultation | `consultation_*` |
| Checkout | CAM 5 `billing_queue`, `checkout_active` |

Normalized scores in `HeatmapCalculator` remain comparable within a store once zones are registered.

---

## Anomaly hooks (existing rules)

| Rule | Zone source |
|------|-------------|
| `QUEUE_SPIKE` | CAM 5 `billing_queue` track count vs baseline |
| `DEAD_ZONE` | Any `browse_*` with zero visits > `dead_zone_minutes` |
| `CONVERSION_DROP` | Funnel ENTRY (CAM 3) vs BILLING_QUEUE (CAM 5) ratio |
| `STALE_FEED` | Per-camera last `vision.frame.processed` timestamp |

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| High angle → bbox drift at zone edges | Use foot point (bottom-center of bbox) for polygon tests |
| Consultation desk confused with billing | Separate zone_types; only CAM 5 `billing_queue` maps to BILLING_QUEUE |
| Staff inflates queue depth | Staff classifier + `checkout_staff` exclusion polygon |
| CAM 3 occlusion | Hard mask zone; never emit events from `occlusion_mask` |
| Overlap double-count | Phase 1: camera-local events only; dedupe at session layer via Re-ID |

---

## Next steps

1. Seed `cameras` + `camera_zones` rows for demo store UUID with proposed polygons.
2. Implement `IZoneAnalyzer` line-crossing + polygon dwell on stub tracks for integration test.
3. Replace stub with YOLO+ByteTrack foot-point zone tests.
4. Record calibration QA video after polygon edit (before/after overlay).
