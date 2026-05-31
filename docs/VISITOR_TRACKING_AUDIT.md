# Visitor Tracking & Re-ID Audit

**Audit date:** 2026-05-30  
**Data source:** Full YOLO run (`pipeline-0734f127c0d7`) — `data/pipeline/events.jsonl` (652 events) + PostgreSQL (467 ingested events, 1 session)  
**Store:** `00000000-0000-0000-0000-000000000101`

---

## Executive answer

**Are all detections assigned the same `visitor_id`?** **No.**

The pipeline produced **21 unique `external_track_id` values** in the JSONL export (22 in PostgreSQL after partial ingest). The dashboard figure of **1 unique visitor** comes from the **`sessions` table** (store-entry lifecycle), not from counting track IDs.

Visitor tracking is **partially functioning**:

| Layer | Status | Notes |
|-------|--------|-------|
| Per-camera ByteTrack + GIR | Working | Distinct IDs per person/track; same-camera recovery merges some ID switches |
| Cross-camera Re-ID | **Not observed** | 0 IDs appear on more than one camera in this run |
| Store ENTRY / EXIT counting | **Under-triggered** | 3 entries, 1 exit on real sparse evening footage |
| Session → funnel KPI | **Working but narrow** | 1 session opened; funnel `unique_visitors = 1` is correct for *sessions*, not footfall |

---

## Requested metrics

### Pipeline output (`events.jsonl`, n=652)

| Metric | Count |
|--------|------:|
| **Total ENTRY events** (`is_store_entry=true`) | **3** |
| **Total EXIT events** (`is_store_exit=true`) | **0** |
| **Entry threshold `direction=in`** | 3 |
| **Entry threshold `direction=out`** (on `zone.entered`) | 1 |
| **Re-entry flagged** (`is_reentry=true`) | **0** |
| **Unique `external_track_id`** | **21** |

### PostgreSQL (ingested subset, n=467)

| Metric | Count |
|--------|------:|
| **Total ENTRY events** (`is_store_entry=true`) | **3** |
| **Total EXIT events** (`is_store_exit=true`) | **1** |
| **Re-entry flagged** | **0** |
| **Unique `external_track_id`** | **22** |
| **Sessions persisted** | **1** |
| **Funnel `unique_visitors` (API)** | **1** |
| **Funnel `re_entry_count` (ENTRY stage)** | **0** |

---

## Top 20 `external_track_id` by event count (full pipeline JSONL)

| Rank | Events | `external_track_id` (suffix) | Share |
|-----:|-------:|--------------------------------|------:|
| 1 | 137 | `…ee10cbcb-07bf-4c86-8238-bbd0fc081053` | 25.7% |
| 2 | 61 | `…81ab0a7d-047e-4ebb-bc72-76e1cb297f77` | 11.4% |
| 3 | 44 | `…7bd8781b-7769-4ddf-9979-fe10a7162bc3` | 8.3% |
| 4 | 37 | `…cbbca6a5-1fe6-415e-b2d5-f03074b64419` | 6.9% |
| 5 | 36 | `…8a309849-d703-486d-a2a3-a16b73297552` | 6.8% |
| 6 | 29 | `…00ac04aa-8244-4d86-bd5c-1385c11bcefb` | 5.4% |
| 7 | 23 | `…6ca4b18f-cfff-4629-af37-c44bd17ffd35` | 4.3% |
| 8 | 20 | `…a626e29e-e0fa-4c2d-b830-f98dd266c867` | 3.8% |
| 9 | 20 | `…9543da8f-086b-4bf2-a524-35b6b3477b95` | 3.8% |
| 10 | 20 | `…fe192eba-b456-425c-8edf-b8715535204f` | 3.8% |
| 11 | 19 | `…4edb1b4f-9964-45d8-94fb-7cf7c5c447d1` | 3.6% |
| 12 | 17 | `…a9ce059a-5de0-4dea-8ee3-1a6e60990cde` | 3.2% |
| 13 | 12 | `…82aa6bb0-d75e-4755-a544-3dd6698958c6` | 2.3% |
| 14 | 9 | `…7af1aa72-bb37-4e70-a4eb-18b270a46625` | 1.7% |
| 15 | 9 | `…d3522f38-2a91-49d5-9196-e909c54fea49` | 1.7% |
| 16 | 8 | `…ab1f4cfc-2bd2-45ee-bf95-c667cee55aab` | 1.5% |
| 17 | 8 | `…ac751382-30fa-48aa-873a-6ae41cbed937` | 1.5% |
| 18 | 7 | `…be669a9f-c016-47cf-b95c-4129c69200e9` | 1.3% |
| 19 | 7 | `…005442fc-a07d-46d4-ad7a-3a53123947f3` | 1.3% |
| 20 | 7 | `…7c728ce4-5842-482b-b64f-51c378b25a59` | 1.3% |

119 events (`vision.frame.processed`) carry track IDs only inside nested `tracks[]` and are excluded from this ranking.

**Concentration:** Top ID holds **25.7%** of events with a top-level `external_track_id`; **2 IDs** exceed 50 events each. This indicates one or two long-lived tracks (likely counter/staff or a stationary shopper), not a single-ID collapse.

---

## Per-camera identity distribution

| Camera | Unique `external_track_id` |
|--------|---------------------------:|
| CAM 1 (floor) | 7 |
| CAM 2 (floor) | 6 |
| CAM 3 (entry) | 3 |
| CAM 4 (backroom) | 0* |
| CAM 5 (billing) | 5 |

\*CAM 4 detections were classified **staff** (`staff_only` zone); staff zone events omit `external_track_id` in several payloads.

**Cross-camera Re-ID links:** **0** — no `external_track_id` appears on more than one camera.

---

## Why “652 events” but “1 unique visitor”?

These metrics measure **different things**:

```
ByteTrack local tracks
    → GlobalIdentityRegistry.resolve()  →  external_track_id  (21–22 distinct)
    → SessionManager.start_or_resume()    →  session row        (1 row)
    → FunnelCalculator.unique_visitors    →  counts sessions    (1)
```

1. **`external_track_id`** — Created in `GlobalIdentityRegistry.resolve()` (`pipeline/tracker.py:356–461`). Each new ByteTrack local ID gets a new UUID unless same-camera recovery or cross-camera embedding match exceeds threshold (`match_score_threshold: 0.68`).

2. **`sessions` / funnel visitor** — Opened only when a track crosses **CAM 3 `entry_threshold` line inward** (`_apply_session_rules`, `tracker.py:1352–1361`). Real YOLO on sparse evening entry footage produced **3 `is_store_entry` events** but only **1 session** was persisted (others may lack stable track continuity or failed ingest FK).

3. **The sessioned visitor is not the busiest track.** The persisted session uses `…82aa6bb0…` (12 events). The noisiest track `…ee10cbcb…` (137 events) never received a store-entry session — consistent with a floor/billing dwell without a confirmed CAM 3 threshold crossing.

---

## Re-ID logic assessment (real YOLO mode)

| Check | Result |
|-------|--------|
| Mock shared embedding forced merge | **Off** — only enabled when `detector.mode=mock` (`tracker.py:1419–1421`) |
| Same-camera track recovery | **Active** — `TrackRecoveryRegistry` + GIR same-camera scoring |
| Cross-camera graph handoff | **Configured** but **0 merges** — appearance cosine + 120–180 s handoff windows not met between sequential per-camera video reads |
| Staff isolation | **Working** — 32 staff-labelled events; staff tracks excluded from customer funnel |
| Track churn | **High** — 331 `vision.track.ended` vs 21 global IDs → ByteTrack drops create new global UUIDs when recovery fails |

Cross-camera Re-ID is **designed for live multi-camera frames**, not for **offline sequential full-clip processing** where CAM 1 finishes before CAM 3 starts. The registry TTL (2700 s) stays hot, but embeddings from CAM 1 persons do not reappear on CAM 3 in a linkable way on this dataset.

---

## ENTRY / EXIT correctness

| Signal | Expected | Observed | Verdict |
|--------|----------|----------|---------|
| Store entry | CAM 3 threshold `direction=in` | 3 | Low but plausible for quiet clip |
| Store exit | Threshold `direction=out` or exit flag | 0–1 | Under-counted |
| Re-entry after cooldown | Second session with `is_reentry` | 0 | No re-entries in clip |
| Zone enters (all types) | Many | 142 | Working |
| Staff backroom | CAM 4 | 12 staff enters | Working |

---

## Conclusion

**Visitor tracking is not collapsing to a single ID.** Re-ID assigns **21+ distinct global identities** with reasonable per-camera diversity. The **“1 unique visitor” dashboard KPI is correct for session-based footfall** but **under-represents** the number of distinct people detected (~21 tracks, many likely staff or repeated ByteTrack fragments).

**Primary gaps:**

1. **Metric mismatch** — Dashboard `unique_visitors` counts **sessions**, not **`external_track_id` cardinality**.
2. **Cross-camera Re-ID inactive** on offline sequential processing + sparse entry detections.
3. **ByteTrack fragmentation** — 331 track endings inflate ID count and suppress session continuity.
4. **Entry gating** — Most floor/billing activity never opens a session without CAM 3 threshold crossing.

**Recommended fixes (priority order):**

1. Add dashboard/API field `unique_tracks_detected` from distinct `external_track_id` for CV diagnostics.
2. Process cameras in **timestamp-interleaved order** (or live mode) for cross-camera Re-ID.
3. Tune CAM 3 entry YOLO threshold (`confidence: 0.32`) and line calibration for real threshold crossings.
4. Increase ByteTrack `track_buffer` / same-camera recovery for YOLO (not just mock).

---

## Verification commands

```powershell
# Re-run analysis on JSONL
python -c "import json; from collections import Counter; from pathlib import Path
ev=[json.loads(l) for l in Path('data/pipeline/events.jsonl').read_text().splitlines() if l.strip()]
ids=Counter(e['payload'].get('external_track_id') for e in ev if e['payload'].get('external_track_id'))
print('unique ids', len(ids), 'top', ids.most_common(3))"

# Funnel API
curl -H "X-API-Key: purple-demo-key" http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel
```
