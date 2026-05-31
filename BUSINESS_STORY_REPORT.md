# Business Story Report

**Generated:** 2026-05-30T18:35:07.140148+00:00  
**Store:** `00000000-0000-0000-0000-000000000101`  
**Period:** 2026-04-30T18:35:05.644674+00:00 → 2026-05-30T18:35:05.644674+00:00

## Executive summary

Store Intelligence connects **CCTV vision events** and **POS transactions** into one
retail funnel. Each shopper progresses through four business stages:

```
  Visitor  →  Zone Visit  →  Billing Queue  →  Purchase
  (CCTV)      (CCTV)          (CCTV)            (POS)
```

| Metric | Value |
|--------|------:|
| Unique visitors (tracks) | **32** |
| Customer sessions | **1** |
| Linked POS purchases | **0** |
| Complete 4-stage journeys | **0** |

---

## 1. Stage definitions

| Business step | Engine stage | Source | How it is detected |
|---------------|--------------|--------|--------------------|
| **Visitor** | `ENTRY` | CCTV pipeline | Customer session started (store entry / CAM 3 threshold) |
| **Zone Visit** | `ZONE_VISIT` | CCTV pipeline | vision.zone.entered — browse, aisle, consultation, promo zones |
| **Billing Queue** | `BILLING_QUEUE` | CCTV pipeline | vision.zone.entered — billing_queue, checkout, queue zones |
| **Purchase** | `PURCHASE` | POS / analytics | Completed transaction or analytics.purchase.completed event |

Staff tracks and `staff_only` zones are excluded from customer funnel metrics.

---

## 2. Funnel counts (live data)

| Business step | Stage | Count | Re-entries | Conversion to next | Drop-off |
|---------------|-------|------:|-----------:|-------------------:|---------:|
| Visitor | `ENTRY` | **2** | 3 | 0.0% | 100.0% |
| Zone Visit | `ZONE_VISIT` | **17** | 105 | 0.0% | 100.0% |
| Billing Queue | `BILLING_QUEUE` | **8** | 10 | 0.0% | 100.0% |
| Purchase | `PURCHASE` | **0** | 0 | — | — |

---

## 3. How conversion is calculated

### Sequential stage conversion

Sequential conversion: for stage S, count visitors who reached both S and the next stage, divide by visitors who reached S, cap at 100%. drop_off_rate = 1 − conversion_rate. PURCHASE is terminal (no downstream rate).

**Worked example (from current data):**

- **Visitor → Zone Visit:** 0 of 2 visitors = **0.0%** conversion, **100.0%** drop-off
- **Zone Visit → Billing Queue:** 0 of 17 visitors = **0.0%** conversion, **100.0%** drop-off
- **Billing Queue → Purchase:** 0 of 8 visitors = **0.0%** conversion, **100.0%** drop-off

### End-to-end purchase conversion

Overall purchase conversion (dashboard KPI): min(PURCHASE.count, ENTRY.count) / ENTRY.count, capped at 100% when POS and CCTV windows differ.

**Current Visitor → Purchase rate:** **0.0%** (`PURCHASE.count=0` / `ENTRY.count=2`, capped at 100%)

### Re-entries

When a visitor re-enters the same stage after the first touch, `re_entry_count` increments but the stage `count` does not — the funnel measures **first-touch** progression.

---

## 4. Linked retail journeys

**Endpoint:** `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys`

| Metric | Value |
|--------|------:|
| Total journey rows | **27** |
| Complete journeys (all 4 stages + POS) | **0** |
| Billing → Purchase (linked tracks) | **0.0%** |

_No complete journeys in period. Run `python scripts/link_pos_journeys.py` after POS ingest._

---

## 5. Dashboard & API

| Surface | Location |
|---------|----------|
| Live dashboard | http://localhost:8000/dashboard/ → **Business story** |
| Funnel API | `GET /api/v1/stores/{id}/funnel` |
| Journeys API | `GET /api/v1/stores/{id}/funnel/journeys` |
| Domain logic | `app/domain/funnel/calculator.py` |

---

## 6. Reproduce

```bash
docker compose up -d
python scripts/setup_videos.py --check
python -m pipeline.run --ingest --persist-sessions --camera "CAM 3" --max-frames 25
python scripts/ingest_pos_csv.py --replace   # optional POS
python scripts/link_pos_journeys.py --clear --mode auto
python scripts/generate_business_story_report.py
```

