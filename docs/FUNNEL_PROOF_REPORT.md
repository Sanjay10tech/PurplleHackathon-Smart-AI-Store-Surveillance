# Funnel Reviewer Proof Report — Purple Tech

**Generated:** 2026-05-30T16:02:25.234645+00:00
**Store:** `00000000-0000-0000-0000-000000000101`
**Overall verdict:** **PASS**

## Funnel stages (first-touch counts)

| Stage | Count | Re-entries | Conversion | Drop-off | Raw events | Distinct tracks |
|-------|------:|-----------:|-----------:|---------:|-----------:|----------------:|
| **ENTRY** | 2 | 3 | 0.0000 | 1.0000 | 4 | 2 |
| **ZONE_VISIT** | 14 | 101 | 0.0000 | 1.0000 | 115 | 14 |
| **BILLING_QUEUE** | 5 | 10 | 0.0000 | 1.0000 | 15 | 5 |
| **PURCHASE** | 0 | 0 | — | — | 0 | 0 |

- **Unique visitors (KPI):** 22
- **Customer sessions:** 1

## Verification checklist

| Check | Result | Detail |
|-------|--------|--------|
| ENTRY first-touch = distinct tracks | **PASS** | funnel=2 sql_distinct=2 raw_events=4 |
| ZONE_VISIT first-touch = distinct tracks | **PASS** | funnel=14 sql_distinct=14 raw_events=115 |
| BILLING_QUEUE first-touch = distinct tracks | **PASS** | funnel=5 sql_distinct=5 raw_events=15 |
| PURCHASE first-touch = distinct tracks | **PASS** | funnel=0 sql_distinct=0 raw_events=0 |
| ENTRY conversion bounded | **PASS** | conversion_rate=0.0 |
| ENTRY drop-off bounded | **PASS** | drop_off_rate=1.0 |
| ZONE_VISIT conversion bounded | **PASS** | conversion_rate=0.0 |
| ZONE_VISIT drop-off bounded | **PASS** | drop_off_rate=1.0 |
| BILLING_QUEUE conversion bounded | **PASS** | conversion_rate=0.0 |
| BILLING_QUEUE drop-off bounded | **PASS** | drop_off_rate=1.0 |
| Re-entries tracked separately | **PASS** | total_re_entries=114 |
| Staff zone events excluded from funnel SQL baseline | **PASS** | staff_events=12 staff_tracks=3 |
| Session-based ENTRY path present | **PASS** | customer_sessions=1 funnel_entry=2 |
| Calculator replay matches API | **PASS** | replay={'ENTRY': 2, 'ZONE_VISIT': 14, 'BILLING_QUEUE': 5, 'PURCHASE': 0} api={'ENTRY': 2, 'ZONE_VISIT': 14, 'BILLING_QUEUE': 5, 'PURCHASE': 0} |
| Zone-only tracks allowed (floor cam without entry line) | **PASS** | entry=2 zone=14 zone_only_tracks=12 |
| audit_funnel.py PASS | **PASS** | ======================================================================== |

## Dimension proofs

### 1. No double counting

Funnel uses **first-touch per visitor per stage**. Raw zone-enter events exceed funnel counts by design:

- ZONE_VISIT: 115 raw enters → **14** visitors (not 115)
- BILLING_QUEUE: 15 raw → **5** visitors

Duplicate stage signals increment `re_entry_count` only.

### 2. No impossible conversions

Conversion rates use **sequential per-visitor logic**: only visitors who reached both
stage *N* and stage *N+1* count toward conversion. Rates are always in `[0, 1]`.

| Transition | Rate | Meaning |
|------------|-----:|---------|
| ENTRY → ZONE_VISIT | 0.0000 | 2 at upstream, 14 at downstream |
| ZONE_VISIT → BILLING_QUEUE | 0.0000 | 14 at upstream, 5 at downstream |
| BILLING_QUEUE → PURCHASE | 0.0000 | 5 at upstream, 0 at downstream |

### 3. Session-based counting

- Customer sessions in DB: **1**
- ENTRY first-touch count: **2** (session start + entry-zone first touch, deduped by track)
- Track-only zone events use synthetic session IDs (`uuid5`) when no DB session exists

### 4. Re-entry handling

| Stage | First-touch | Re-entries |
|-------|------------:|-----------:|
| ENTRY | 2 | 3 |
| ZONE_VISIT | 14 | 101 |
| BILLING_QUEUE | 5 | 10 |
| PURCHASE | 0 | 0 |

**Total re-entries:** 114 (never added to stage `count`)

### 5. Staff exclusion

- Staff/ignore zone events in DB: **12** (3 tracks)
- Staff signals blocked at ingest filter: **12**
- Staff sessions rejected in `_event_to_signal` / `_purchase_to_signal`
- Customer SQL baseline excludes `class_label=staff` and `staff_only`/`ignore` zones

### Track overlap (same `external_track_id` across stages)

| Transition | Shared tracks |
|------------|----------------:|
| ENTRY ∩ ZONE_VISIT | 0 |
| ZONE_VISIT ∩ BILLING_QUEUE | 0 |
| ENTRY ∩ BILLING_QUEUE | 0 |

Sequential conversion uses per-track journey replay. When overlap is **0**,
conversion rates reflect **disjoint track populations** in the ingested CCTV data
(entry cam tracks vs floor cam tracks vs billing cam tracks), not a funnel logic error.

## Automated audit log

```text
2026-05-30 21:32:24 [info     ] funnel_computed                dedupe_strategy=external_track_id entry_count=2 session_count=1 store_id=00000000-0000-0000-0000-000000000101 unique_visitors=22
========================================================================
CONVERSION FUNNEL AUDIT
========================================================================

Store: 00000000-0000-0000-0000-000000000101
DB events ingested: 467
Pipeline JSONL events generated: 652
Unique visitors (SQL): 22
Sessions: 1

--- 1. Raw counts by event_type ---
  vision.zone.entered            events= 146  distinct_tracks=21
  vision.track.ended             events= 136  distinct_tracks=22
  vision.frame.processed         events= 123  distinct_tracks=0
  vision.zone.exited             events=  62  distinct_tracks=15

--- 2-5. Funnel stages: raw events | distinct tracks | aggregated | dashboard ---
  ENTRY          raw=   4  expected=  2  aggregated=  2  dashboard=  2  [OK]
  ZONE_VISIT     raw= 115  expected= 14  aggregated= 14  dashboard= 14  [OK]
  BILLING_QUEUE  raw=  15  expected=  5  aggregated=  5  dashboard=  5  [OK]
  PURCHASE       raw=   0  expected=  0  aggregated=  0  dashboard=  0  [OK]

========================================================================
BEFORE (broken session-gated funnel)
{
  "unique_visitors": 22,
  "ENTRY": 1,
  "ZONE_VISIT": 0,
  "BILLING_QUEUE": 0,
  "PURCHASE": 0
}

AFTER (current)
{
  "ENTRY": 2,
  "ZONE_VISIT": 14,
  "BILLING_QUEUE": 5,
  "PURCHASE": 0,
  "unique_visitors": 22
}

PASS
========================================================================
```

## Reproduce

```bash
python scripts/audit_funnel.py
python scripts/audit_funnel_extended.py
python scripts/generate_funnel_proof_report.py
pytest tests/unit/test_funnel_calculator.py tests/test_funnel_service.py tests/scenarios/test_reentry.py
```

---

*Purple Tech funnel proof: **PASS***
