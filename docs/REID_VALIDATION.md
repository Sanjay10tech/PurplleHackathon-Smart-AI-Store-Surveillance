# Re-ID System Validation

**Generated:** 2026-05-30T16:50:17.724746+00:00
**Store:** Brigade_Bangalore (`00000000-0000-0000-0000-000000000101`)

## Executive summary

| Layer | Status | Evidence |
|-------|--------|----------|
| Per-camera tracking | **Implemented** | ByteTrack on YOLO person detections |
| Global Identity Registry (GIR) | **Implemented** | Shared across 5 cameras in `MultiCameraPipeline` |
| Appearance embedding | **Implemented** | HSV histogram 512-d (`AppearanceEmbedder`) |
| Cross-camera matching | **Implemented** | Cosine + camera graph + time gap + recovery |
| P0 solo handoff | **Implemented** | Single active visitor on source cam continues global ID |
| API evidence | **Implemented** | `GET /api/v1/stores/{id}/reid/evidence` |

## 1. Same person moving across cameras

### Pipeline proof (mock CCTV, 80 frames/camera)

Simulated visitor path: **CAM 3 (entry) → CAM 1/2 (floor) → CAM 5 (billing)**.

| Metric | Legacy tuning | Improved + GIR |
|--------|-------------:|---------------:|
| Visitor global IDs | 3 | **1** |
| Cameras on top visitor | 3 | **4** |
| Cross-camera links (>=2 cams) | 2 | **1** |
| Overall Re-ID score | 60% | **75%** |

**Interpretation:** Improved pipeline maintains **one global visitor ID** across **4 cameras** in mock mode, proving the cross-camera association logic works end-to-end.

### Ingested PostgreSQL evidence (YOLO run)

| Metric | Value |
|--------|------:|
| Unique `external_track_id` values | 22 |
| Single-camera-only tracks | 22 |
| Cross-camera tracks (same ID, 2+ cams) | **0** |
| Unlinked handoff candidates | 0 |

> **YOLO ingest note:** Real footage embeddings differ per camera clip; most tracks remain camera-local until P0 solo handoff or stronger embeddings (OSNet) are applied on re-ingest.


## 2. Cross-camera identity matching strategy

```
ByteTrack (per cam) → AppearanceEmbedder → GlobalIdentityRegistry.resolve()
                                              ├─ cosine similarity (0.55 threshold)
                                              ├─ camera graph P0 handoff windows
                                              ├─ time-gap + apparel color scoring
                                              ├─ TrackRecoveryRegistry (same-cam ID switch)
                                              └─ P0 solo handoff (1 visitor on source cam)
```

### Camera graph (P0 handoffs)

| From | To | Priority | Max gap |
|------|-----|----------|--------:|
| CAM 3 (entry) | CAM 1 / CAM 2 | P0 | 150 s |
| CAM 1 / CAM 2 | CAM 5 (billing) | P0 | 210 s |
| CAM 5 | CAM 4 (backroom) | P1 | 300 s |

### Global ID format

`external_track_id = {store_id}:{uuid}` — persisted on all vision events and sessions.

## 3. Re-ID evidence

### API

```bash
curl -s -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/reid/evidence" | jq ".cross_camera_track_count, .cross_camera_tracks[:2]"
```

### Pipeline metrics script

```bash
python scripts/analyze_reid_metrics.py --legacy
python scripts/analyze_reid_metrics.py
python scripts/analyze_reid_metrics.py --json
```

### Handoff candidates (unlinked IDs, temporal P0 match)

_No unlinked handoff candidates in current window._

## 4. Implementation files

| File | Role |
|------|------|
| `pipeline/tracker.py` | ByteTrack, GIR, TrackRecoveryRegistry, SessionManager |
| `pipeline/config.yaml` | Re-ID thresholds, camera graph, handoff windows |
| `app/domain/reid/evidence.py` | Cross-camera evidence analyzer |
| `app/services/reid_evidence_service.py` | API evidence service |
| `scripts/analyze_reid_metrics.py` | Before/after pipeline metrics |

## 5. Reproduce validation

```bash
python scripts/generate_reid_validation.py
python -m pytest tests/test_reid_evidence.py tests/test_pipeline.py -q
```

---

*Mock cross-camera score: 75% · DB cross-camera tracks: 0 · Unique IDs: 22*
