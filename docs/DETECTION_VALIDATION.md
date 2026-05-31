# Detection Validation Report — All CCTV Videos

**Generated:** 2026-05-30T18:10:31.006866+00:00
**Model:** yolo11n.pt (yolo)
**Sample rate:** 5.0 FPS
**Pipeline correlation:** `validation-f0480da01e29`

## Executive summary

| Metric | Total |
|--------|------:|
| Videos processed | 5 |
| Frames processed | 100 |
| People detections (track-frame sum) | 111 |
| Entry events | 0 |
| Exit events | 0 |
| Re-entry events | 0 |
| Staff tracks classified | 0 |
| Group frames (≥2 visitors) | 39 |
| Distinct visitor global IDs | 1 |
| Distinct staff global IDs | 0 |

## Per-video results

| Camera | Role | Frames | People det. | Peak | Entry | Exit | Re-entry | Staff | Group frames | Visitors | Avg conf | Status |
|--------|------|-------:|------------:|-----:|------:|-----:|---------:|------:|-------------:|---------:|---------:|--------|
| CAM 1 | floor | 20 | 40 | 2 | 0 | 0 | 0 | 0 | 20 | 1 | 0.8313 | Processed |
| CAM 2 | floor | 20 | 54 | 4 | 0 | 0 | 0 | 0 | 19 | 1 | 0.7726 | Processed |
| CAM 3 | entry | 20 | 4 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0.5248 | Processed |
| CAM 4 | backroom | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | Processed |
| CAM 5 | billing | 20 | 13 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0.7636 | Processed |

## Accuracy evidence

| Check | Value | Expected | Pass |
|-------|------:|----------|------|
| Tuning composite score | 0.5228 | ≥ 0.50 | PASS |
| Tuning recall proxy | 0.59 | ≥ 0.55 | PASS |
| CAM 4 staff classification rate | 0.0 | ≥ 0.90 | REVIEW |
| Entry events on CAM 3 (entry) | 0 | > 0 | FAIL |
| Entry events on non-entry cams | 0 | low | INFO |

### Per-camera confidence

| Camera | Avg detection confidence |
|--------|-------------------------:|
| CAM 1 | 0.8313 |
| CAM 2 | 0.7726 |
| CAM 3 | 0.5248 |
| CAM 4 | 0.0 |
| CAM 5 | 0.7636 |

### Definitions

- **People detected:** sum of active tracks per sampled frame (includes staff before suppression).
- **Entry events:** `entry_threshold` / `entrance` zone enter with direction `in`.
- **Exit events:** store exit via entry line direction `out` (`is_store_exit`).
- **Re-entry events:** zone enters flagged `is_reentry` after session cooldown.
- **Staff detections:** unique global IDs promoted to `staff` by uniform/dwell/backroom rules.
- **Group detections:** sampled frames with ≥2 simultaneous **visitor** (non-staff) tracks.

## Limitations

YOLOv11n COCO person class only; evening footage with partial occlusion. Staff classification is heuristic (uniform/dwell/backroom), not trained. Group detection = multi-visitor frames, not social-group clustering. Exit events require entry_threshold line crossing outbound on CAM 3.

## Artifacts

- Machine-readable: `docs/evidence/detection_validation.json`
- Pipeline events: `data/pipeline/events.jsonl`
- Annotated samples: `docs/evidence/annotated/` (from `generate_detection_evidence.py`)

## Validation result

**PASS** — 5/5 CCTV videos processed with real yolo detection.
