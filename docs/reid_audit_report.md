# Re-ID & Visitor Tracking Audit Report

**Generated:** 2026-05-30  
**Pipeline run:** `pipeline-0734f127c0d7` (real YOLO, all 5 CCTV videos)  
**Primary artifact:** `data/pipeline/events.jsonl` (652 events)  
**PostgreSQL (ingested):** 467 events, 1 session  
**Store:** `00000000-0000-0000-0000-000000000101`

---

## Summary metrics

| # | Metric | JSONL (full run) | PostgreSQL (ingested) |
|---|--------|-----------------:|----------------------:|
| 1 | **Total ENTRY events** | **3** | **3** |
| 2 | **Total EXIT events** | **1** | **1** |
| 3 | **Total unique `visitor_id` (`external_track_id`)** | **21** | **22** |
| 4 | **Total REENTRY events** | **0** | **0** |
| 5 | **Sessions (funnel visitors)** | 1 | 1 |

**ENTRY** = `vision.zone.entered` with `is_store_entry=true` (CAM 3 entry threshold, direction=in).  
**EXIT** = any event with `is_store_exit=true`.  
**REENTRY** = any event with `is_reentry=true`.

---

## Top 20 `visitor_id` by event count

Events counted when `external_track_id` appears on zone/track payloads (533 tagged events in JSONL).

| Rank | Events | Camera(s) | `external_track_id` |
|-----:|-------:|-----------|---------------------|
| 1 | 137 | CAM 2 | `…ee10cbcb-07bf-4c86-8238-bbd0fc081053` |
| 2 | 61 | CAM 2 | `…81ab0a7d-047e-4ebb-bc72-76e1cb297f77` |
| 3 | 44 | CAM 2 | `…7bd8781b-7769-4ddf-9979-fe10a7162bc3` |
| 4 | 37 | CAM 1 | `…cbbca6a5-1fe6-415e-b2d5-f03074b64419` |
| 5 | 36 | CAM 1 | `…8a309849-d703-486d-a2a3-a16b73297552` |
| 6 | 33 | CAM 5 | `…00ac04aa-8244-4d86-bd5c-1385c11bcefb` |
| 7 | 23 | CAM 3 | `…a9ce059a-5de0-4dea-8ee3-1a6e60990cde` |
| 8 | 23 | CAM 5 | `…6ca4b18f-cfff-4629-af37-c44bd17ffd35` |
| 9 | 22 | CAM 5 | `…fe192eba-b456-425c-8edf-b8715535204f` |
| 10 | 20 | CAM 1 | `…a626e29e-e0fa-4c2d-b830-f98dd266c867` |
| 11 | 20 | CAM 1 | `…9543da8f-086b-4bf2-a524-35b6b3477b95` |
| 12 | 19 | CAM 2 | `…4edb1b4f-9964-45d8-94fb-7cf7c5c447d1` |
| 13 | 13 | CAM 3 | `…82aa6bb0-d75e-4755-a544-3dd6698958c6` |
| 14 | 10 | CAM 5 | `…7c728ce4-5842-482b-b64f-51c378b25a59` |
| 15 | 9 | CAM 1 | `…7af1aa72-bb37-4e70-a4eb-18b270a46625` |
| 16 | 9 | CAM 5 | `…d3522f38-2a91-49d5-9196-e909c54fea49` |
| 17 | 8 | CAM 2 | `…ab1f4cfc-2bd2-45ee-bf95-c667cee55aab` |
| 18 | 8 | CAM 2 | `…ac751382-30fa-48aa-873a-6ae41cbed937` |
| 19 | 8 | CAM 3 | `…005442fc-a07d-46d4-ad7a-3a53123947f3` |
| 20 | 7 | CAM 1 | `…be669a9f-c016-47cf-b95c-4129c69200e9` |

Top ID share: **25.7%** of tagged events. **No single ID dominates 100% of traffic.**

---

## Collision analysis — are multiple people sharing one `visitor_id`?

### Test 1: Global collapse (all events → one ID)

| Result | **FAIL concern ruled out** |
|--------|----------------------------|
| Unique IDs | 21 (JSONL) / 22 (DB) |
| Verdict | System does **not** assign all detections to one visitor. |

### Test 2: Cross-camera same ID (impossible without Re-ID link)

| Result | **PASS** |
|--------|----------|
| IDs appearing on 2+ cameras | **0** |
| Temporal overlap (same ID, two cameras ≤120 s) | **0** |
| Verdict | No cross-camera over-merge detected. Cross-camera Re-ID did **not** incorrectly fuse separate people. |

### Test 3: Same frame, same camera, multiple local tracks → one global ID

| Result | **FAIL — localized over-merge** |
|--------|----------------------------------|
| `vision.frame.processed` frames with duplicate `external_track_id` | **43 frames** |
| Distinct global IDs involved | **12** |
| Example (CAM 1, frame 0) | Local tracks **1** and **2** both mapped to `…8a309849…` |
| Example (CAM 1, frame 720) | Local tracks **7, 1, 2** all mapped to `…8a309849…` |

**Interpretation:** When YOLO detects **two or more people in one frame**, `GlobalIdentityRegistry.resolve()` sometimes assigns the **same global UUID** to **different ByteTrack local IDs** on the **same camera at the same timestamp**. That is physically impossible (one person cannot occupy two boxes) and indicates **incorrect same-camera Re-ID / recovery**.

Most affected IDs:

| Global ID suffix | In-frame duplicate frames |
|------------------|--------------------------:|
| `…8a309849…` | 10 |
| `…ee10cbcb…` | 8 |
| `…7bd8781b…` | 7 |
| `…cbbca6a5…` | 6 |
| `…81ab0a7d…` | 6 |

### Test 4: Same camera, one global ID, many local track IDs (sequential recovery)

| Result | **Expected / mixed** |
|--------|----------------------|
| Global IDs with 2+ local track IDs on one camera | **25** |
| Max local tracks under one global ID | **28** (CAM 2 `…ee10cbcb…`) |

Sequential local ID changes are **expected** when ByteTrack drops and GIR recovers the same person. This becomes **incorrect** when local IDs are **simultaneous** (Test 3).

---

## ENTRY / EXIT / REENTRY detail

| Signal | Count | Notes |
|--------|------:|-------|
| `entry_threshold` direction=in | 3 | CAM 3 entry line |
| `entry_threshold` direction=out (on zone.entered) | 1 | Exit-side crossing |
| `is_store_entry` | 3 | Opens / resumes sessions |
| `is_store_exit` | 1 | Closes session path |
| `is_reentry` | 0 | No cooldown re-entries |
| Zone enters (all types) | 142 | Aisle, billing, staff, etc. |
| `vision.track.ended` | 331 | High ByteTrack churn |

**Session persisted:** 1 row — `external_track_id` = `…82aa6bb0…` (CAM 3 entry visitor, 13 tagged events).  
**Not the busiest track** (top ID `…ee10cbcb…` has 137 events but no store-entry session).

---

## Re-ID configuration (real YOLO mode)

| Setting | Value | Effect on this run |
|---------|-------|-------------------|
| `reid.enabled` | true | GIR active |
| `mock_shared_visitor_embedding` | **off** | No forced single visitor |
| `match_score_threshold` | 0.68 | Cross-camera merge bar not met |
| `same_camera_cosine_threshold` | 0.40 | **Low bar → aggressive same-camera merge** |
| `same_camera_recovery_enabled` | true | Recovers lost tracks to prior global ID |
| Processing mode | Offline sequential per camera | Cross-camera handoff unused |

---

## Verdict

| Question | Answer |
|----------|--------|
| Are all 652 events under one `visitor_id`? | **No** — 21 distinct IDs |
| Are multiple people ever given the same `visitor_id`? | **Yes** — **43 frames** show 2+ simultaneous local tracks sharing one global ID (12 IDs affected) |
| Is cross-camera Re-ID over-merging? | **No** — zero cross-camera IDs |
| Is visitor/session tracking correct for funnel? | **Partially** — 3 ENTRY signals, 1 session, 0 re-entries; floor traffic mostly untracked as visitors |
| Root cause of “1 unique visitor” KPI | Funnel counts **sessions**, not **`external_track_id`** cardinality |

**Overall:** Re-ID is **not** collapsing the whole store to one person, but **same-camera GIR recovery is over-aggressive** and merges **concurrent** detections into one global identity. Fix: disallow global ID reuse when another active local track on the same camera already holds that ID in the current frame, and raise `same_camera_cosine_threshold` for real YOLO.

---

## Recommended fixes

1. **In `GlobalIdentityRegistry.resolve()`** — reject merge if an active track on the same camera already uses the candidate global ID in the current frame.
2. **Raise `same_camera_cosine_threshold`** from 0.40 → ≥0.55 for YOLO mode.
3. **Expose `unique_tracks_detected`** on dashboard separate from `unique_visitors` (sessions).
4. **Interleave cameras by timestamp** for offline runs to enable legitimate cross-camera linking without false same-frame merges.

---

## Reproduce

```powershell
python -c "
import json; from collections import Counter; from pathlib import Path
ev=[json.loads(l) for l in Path('data/pipeline/events.jsonl').read_text().splitlines() if l.strip()]
entry=sum(1 for e in ev if e.get('payload',{}).get('is_store_entry'))
exit_=sum(1 for e in ev if e.get('payload',{}).get('is_store_exit'))
re=sum(1 for e in ev if e.get('payload',{}).get('is_reentry'))
ids=Counter(e['payload']['external_track_id'] for e in ev if e.get('payload',{}).get('external_track_id'))
print('ENTRY',entry,'EXIT',exit_,'REENTRY',re,'UNIQUE',len(ids))
"
```
