# Detection Evidence — Real YOLO on CCTV

**Generated:** 2026-05-30T08:57:59.134006+00:00
**Model:** yolo11n.pt

## Summary

| Camera | Frames | Detections | Avg confidence | Status |
|--------|-------:|-----------:|---------------:|--------|
| CAM 3 | 20 | 27 | 0.522 | OK |
| CAM 1 | 20 | 41 | 0.821 | OK |
| CAM 5 | 20 | 14 | 0.75 | OK |

## Artifacts

- Annotated frames: `docs/evidence/annotated/`
- Tracking screenshots: `docs/evidence/tracking/`
- Sample events: `docs/evidence/sample_events.json`

## Observed accuracy and limitations

YOLOv11n detects COCO `person` class only; crowded scenes may merge boxes. ByteTrack ID switches under occlusion are mitigated by session rules but not eliminated. Staff uniform heuristic is rule-based, not trained. Zone lines require manual calibration per store.

## Pipeline sample run

- Exit code: 0
- Sample events captured: 4