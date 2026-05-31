# Brigade Road Layout Validation Report

**Generated:** 2026-05-30T16:07:02.644761+00:00
**Store:** Brigade_Bangalore (`00000000-0000-0000-0000-000000000101`) · **Code:** ST1008
**Excel source:** `Brigade_Road_Layout.xlsx` (revision labels: Revised / Current)
**Floor plan image:** `docs\evidence\brigade_road_layout.png`

## Executive summary

| Check | Status |
|-------|--------|
| Excel floor plan parsed | PASS | 21 brand/zone labels extracted |
| Layout YAML loaded | PASS | 17 physical zones |
| CCTV → layout mapping | PASS | 18 camera zones mapped |
| Heatmap layout alignment | PASS | keys use `layout:` prefix |
| Generic names replaced | PASS | store zone labels on all CCTV polygons |

## 1. Layout mapping (CCTV → store floor plan)

| Camera | zone_id | Generic (before) | Store zone (after) | layout_zone_id | DB events |
|--------|---------|------------------|--------------------|----------------|-----------|
| CAM 1 | `zone-cam1-aisle` | foh_circulation | **Front of House (F.O.H.)** | `foh_circulation` | yes |
| CAM 1 | `zone-cam1-aisle-entry-line` | foh_circulation_entry_line | **Front of House (F.O.H.)** | `foh_circulation` | no |
| CAM 1 | `zone-cam1-browse-left` | skincare_wall | **Skincare Brand Wall** | `skincare_wall` | no |
| CAM 1 | `zone-cam1-consultation` | consultation_skincare | **Skincare Consultation Desk** | `consultation_skincare` | yes |
| CAM 1 | `zone-cam1-promo` | promo_island_central | **Promo Island - Beat the Heat** | `promo_island_central` | yes |
| CAM 2 | `zone-cam2-aisle` | foh_circulation | **Front of House (F.O.H.)** | `foh_circulation` | yes |
| CAM 2 | `zone-cam2-browse` | cosmetics_wall | **Cosmetics Brand Wall** | `cosmetics_wall` | no |
| CAM 2 | `zone-cam2-consultation` | consultation_makeup | **Makeup Consultation Station** | `consultation_makeup` | yes |
| CAM 2 | `zone-cam2-left-mouth` | foh_circulation_left_mouth | **Front of House (F.O.H.)** | `foh_circulation` | no |
| CAM 2 | `zone-cam2-promo` | promo_island_south | **Promo Island - Summer Essentials** | `promo_island_south` | yes |
| CAM 3 | `zone-cam3-entry-landing` | entrance_landing | **Store Entrance** | `entrance` | no |
| CAM 3 | `zone-cam3-entry-threshold` | entrance_threshold | **Store Entrance** | `entrance` | yes |
| CAM 4 | `zone-cam4-door` | stockroom_door | **Stockroom** | `stockroom` | no |
| CAM 4 | `zone-cam4-stock` | stockroom | **Stockroom** | `stockroom` | no |
| CAM 5 | `zone-cam5-checkout` | cash_counter | **Cash Counter** | `cash_counter` | yes |
| CAM 5 | `zone-cam5-queue` | billing_queue | **Billing Queue** | `billing_queue` | yes |
| CAM 5 | `zone-cam5-queue-entry` | billing_queue_entry_line | **Billing Queue** | `billing_queue` | no |
| CAM 5 | `zone-cam5-staff` | cash_counter_staff | **Cash Counter** | `cash_counter` | yes |

## 2. Zone coordinates

### 2a. CCTV normalized polygons (pipeline/zones.yaml)

| Camera | Store zone | Type | Coordinates (normalized 0–1) |
|--------|------------|------|----------------------------|
| CAM 1 | Front of House (F.O.H.) | `aisle` | `[0.05, 0.4]; [0.95, 0.4]; [0.95, 0.95]; [0.05, 0.95]` |
| CAM 1 | Promo Island - Beat the Heat | `promo_island` | `[0.35, 0.62]; [0.55, 0.62]; [0.55, 0.88]; [0.35, 0.88]` |
| CAM 1 | Skincare Consultation Desk | `consultation` | `[0.72, 0.55]; [0.95, 0.55]; [0.95, 0.85]; [0.72, 0.85]` |
| CAM 1 | Skincare Brand Wall | `browse_skincare` | `[0.02, 0.08]; [0.98, 0.08]; [0.98, 0.35]; [0.02, 0.35]` |
| CAM 1 | Front of House (F.O.H.) | `aisle` | `line [0.05, 0.9] → [0.95, 0.9]` |
| CAM 2 | Front of House (F.O.H.) | `aisle` | `[0.05, 0.35]; [0.95, 0.35]; [0.95, 0.95]; [0.05, 0.95]` |
| CAM 2 | Makeup Consultation Station | `consultation` | `[0.06, 0.45]; [0.28, 0.45]; [0.28, 0.75]; [0.06, 0.75]` |
| CAM 2 | Cosmetics Brand Wall | `browse_cosmetics` | `[0.02, 0.05]; [0.98, 0.05]; [0.98, 0.32]; [0.02, 0.32]` |
| CAM 2 | Promo Island - Summer Essentials | `promo_island` | `[0.38, 0.68]; [0.58, 0.68]; [0.58, 0.92]; [0.38, 0.92]` |
| CAM 2 | Front of House (F.O.H.) | `aisle` | `line [0.1, 0.3] → [0.1, 0.8]` |
| CAM 3 | Store Entrance | `entry_threshold` | `line [0.42, 0.33] → [0.68, 0.48]` |
| CAM 3 | Store Entrance | `entrance` | `[0.05, 0.25]; [0.55, 0.25]; [0.55, 0.55]; [0.05, 0.55]` |
| CAM 4 | Stockroom | `staff_only` | `[0.05, 0.15]; [0.95, 0.15]; [0.95, 0.95]; [0.05, 0.95]` |
| CAM 4 | Stockroom | `staff_only` | `line [0.35, 0.08] → [0.55, 0.08]` |
| CAM 5 | Billing Queue | `billing_queue` | `[0.05, 0.45]; [0.35, 0.45]; [0.35, 0.88]; [0.05, 0.88]` |
| CAM 5 | Cash Counter | `checkout` | `[0.3, 0.35]; [0.62, 0.35]; [0.62, 0.65]; [0.3, 0.65]` |
| CAM 5 | Cash Counter | `staff_only` | `[0.28, 0.3]; [0.65, 0.3]; [0.65, 0.55]; [0.28, 0.55]` |
| CAM 5 | Billing Queue | `billing_queue` | `line [0.2, 0.45] → [0.2, 0.88]` |

### 2b. Floor plan label anchors (from Excel drawing)

Coordinates normalized to embedded floor-plan image (0=left/top, 1=right/bottom).

| Label (Excel) | plan_x | plan_y | Revision |
|---------------|-------:|-------:|----------|
| Foxtale | 0.7 | 0.0754 | current |
| Minimalist | 0.4968 | 0.0776 | current |
| Aqualogica | 0.601 | 0.0776 | current |
| JC | 0.7968 | 0.0776 | current |
| Accessories | 0.9248 | 0.6844 | current |
| Mens | 0.5255 | 0.8603 | current |
| Beauty | 0.8074 | 0.8625 | current |
| Lo'real | 0.7202 | 0.8736 | current |
| Alps Goodness | 0.6276 | 0.8758 | current |
| Pilgrim | 0.7 | 1.2971 | current |
| D&K | 0.7968 | 1.2993 | current |
| TFS | 0.2117 | 0.0665 | revised |
| Salm | 0.1223 | 0.0687 | revised |
| GV | 0.3127 | 0.0754 | revised |
| DermDoc | 0.4032 | 0.0843 | revised |
| Mars+ | 0.4361 | 0.8536 | revised |
| Faces | 0.2425 | 0.8736 | revised |
| Lakme | 0.3404 | 0.8824 | revised |
| Maybelline | 0.1415 | 0.8847 | revised |
| EB | 0.1223 | 1.2904 | revised |
| Swiss + Renee | 0.4351 | 2.0797 | revised |

### 2c. Physical layout zones (brigade_road_layout.yaml)

| layout_zone_id | Label | Section | Plan position |
|----------------|-------|---------|---------------|
| `accessories_wall` | Accessories Wall | impulse | far_east |
| `billing_queue` | Billing Queue | checkout | east |
| `cash_counter` | Cash Counter | checkout | east |
| `consultation_makeup` | Makeup Consultation Station | service | west_center |
| `consultation_skincare` | Skincare Consultation Desk | service | east_north |
| `cosmetics_wall` | Cosmetics Brand Wall | cosmetics | south |
| `entrance` | Store Entrance | entrance | west |
| `foh_circulation` | Front of House (F.O.H.) | foh | center |
| `fragrance_nails` | Fragrance & Nail Gondola | impulse | west_center |
| `haircare_bay` | Haircare Bay (Alps / L'Oreal) | hair | southeast_wall |
| `makeup_trial_units` | Makeup Trial Units | service | center |
| `mens_care` | Men's Care | skincare | south_mid |
| `pmu_station` | PMU Station | service | southeast |
| `promo_island_central` | Promo Island - Beat the Heat | promo | center_north |
| `promo_island_south` | Promo Island - Summer Essentials | promo | center_south |
| `skincare_wall` | Skincare Brand Wall | skincare | north |
| `stockroom` | Stockroom | back_of_house | back |

## 3. Heatmap alignment

| zone_key | zone_label | section | visits | layout match |
|----------|------------|---------|-------:|--------------|
| `layout:foh_circulation` | Front of House (F.O.H.) | Front of House | 64 | yes |
| `layout:promo_island_south` | Promo Island — Summer Essentials | Promo Islands | 32 | yes |
| `layout:consultation_skincare` | Skincare Consultation Desk | Consultation & Services | 12 | yes |
| `layout:cash_counter` | Cash Counter | Cash Counter & Queue | 11 | yes |
| `layout:consultation_makeup` | Makeup Consultation Station | Consultation & Services | 5 | yes |
| `layout:billing_queue` | Billing Queue | Cash Counter & Queue | 4 | yes |
| `layout:entrance` | Store Entrance | Entrance | 4 | yes |
| `layout:promo_island_central` | Promo Island — Beat the Heat | Promo Islands | 2 | yes |

**Total heatmap visits:** 134
**Layout remapping active:** True

## 4. Missing mappings

### 4a. Camera zones with DB events but no layout mapping

- None

### 4b. Pipeline zones without layout_zone_id

- None

### 4c. Layout zones without CCTV coverage (plan-only)

- `accessories_wall` — **Accessories Wall** (impulse)
- `fragrance_nails` — **Fragrance & Nail Gondola** (impulse)
- `haircare_bay` — **Haircare Bay (Alps / L'Oreal)** (hair)
- `makeup_trial_units` — **Makeup Trial Units** (service)
- `mens_care` — **Men's Care** (skincare)
- `pmu_station` — **PMU Station** (service)

## 5. Brand bays (Excel Current revision — north/south walls)

**North Wall:**
- EB Korean (`bay_eb_korean`)
- The Face Shop (`bay_tfs`)
- Good Vibes (`bay_good_vibes`)
- DermDoc (`bay_dermdoc`)
- Minimalist (`bay_minimalist`)
- Aqualogica (`bay_aqualogica`)
- Pilgrim (`bay_pilgrim`)

**South Wall:**
- Maybelline (`bay_maybelline`)
- Faces Canada (`bay_faces_canada`)
- Lakme (`bay_lakme`)
- Swiss Beauty + Renee (`bay_swiss_renee`)
- Mars + NY Bae (`bay_mars_nybae`)
- Alps Goodness (`bay_alps_goodness`)
- L'Oreal / Streax (`bay_loreal`)
- Beauty Essentials (`bay_beauty_essentials`)

## 6. Validation result

**Overall:** PASS

Regenerate: `python scripts/analyze_brigade_layout.py`
