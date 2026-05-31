# Real Pipeline Validation Evidence

**Generated:** 2026-05-30T18:13:20.621290+00:00  
**Detector:** YOLOv11 (`yolo11n.pt`) — **real inference, no mock**  
**Videos:** Brigade Road CCTV (`data/videos/CAM 1–5.mp4`)  
**Validation frames/camera:** 20 (detection sweep) / ingest proof on CAM 3, 1, 5

## Executive summary

| Claim | Evidence |
|-------|----------|
| Real YOLO on CCTV MP4s | `yolo` mode, model `yolo11n.pt` |
| Videos processed | **5** / 5 |
| Frames analyzed | **100** |
| People detections | **111** |
| Pipeline ingest (real YOLO) | **3** / 3 cameras |
| `validate_submission.py` | **10/10 checks passed** |

> Mock trajectories are **opt-in only** (`python scripts/validate_submission.py --mock`).
> Default validation runs Ultralytics YOLO on real footage.

---

## 1. CCTV video source

All five MP4 files present under `data/videos/`.

---

## 2. Full detection validation (real YOLO)

| Camera | Frames | Detections | Avg conf. | Zone enters | Staff tracks | Status |
|--------|-------:|-----------:|----------:|------------:|-------------:|--------|
| CAM 1 | 20 | 40 | 0.8313 | 3 | 0 | Processed |
| CAM 2 | 20 | 54 | 0.7726 | 4 | 0 | Processed |
| CAM 3 | 20 | 4 | 0.5248 | 0 | 0 | Processed |
| CAM 4 | 20 | 0 | 0.0 | 0 | 0 | Processed |
| CAM 5 | 20 | 13 | 0.7636 | 1 | 0 | Processed |

Processing time: **69.8s**  
Correlation ID: `validation-f0480da01e29`  
JSON: [`docs/evidence/detection_validation.json`](docs/evidence/detection_validation.json)

---

## 3. Ingest proof (real YOLO → API)

Command pattern (default — no `--mock`):

```bash
python -m pipeline.run --ingest --persist-sessions --camera "CAM 3" --max-frames 25
```

| Camera | Mode | Exit | Result |
|--------|------|-----:|--------|
| CAM 3 | yolo | 0 | PASS |
| CAM 1 | yolo | 0 | PASS |
| CAM 5 | yolo | 0 | PASS |

---

## 4. Submission validator

Default:

```bash
python scripts/validate_submission.py
```

Optional mock (CI/dev only):

```bash
python scripts/validate_submission.py --mock
```

### Check output

```
Store Intelligence — submission validation (real YOLO default)

[PASS] data/videos present
       5 MP4 files found
[PASS] GET /health
       status=ok, feed=fresh
[PASS] GET /health/ready
       database up
[PASS] pipeline ingest (real YOLO)
       yolo11n.pt · CAM 3:   api: {'posted': 3, 'accepted': 2, 'rejected': 1, 'duplicate': 0, 'batches': 1}; CAM 1:   api: {'posted': 6, 'accepted': 6, 'rejected': 0, 'duplicate': 0, 'batches': 1}; CAM 5:   api: {'posted': 5, 'accepted': 4, 'rejected': 1, 'dup
[PASS] metrics available (projector or script)
       Projected 3 footfall metric bucket(s) for store 00000000-0000-0000-0000-000000000101
[PASS] GET /metrics
       series_points=2, source=store_metrics
[PASS] GET /funnel
       ENTRY count=2, rates bounded
[PASS] GET /heatmap
       zones=8
[PASS] GET /anomalies
       items=0
[PASS] GET /health after checks
       status=ok, feed=fresh

10/10 checks passed
```

---

## 5. Reproduce

```bash
pip install -e ".[dev,pipeline]"
python scripts/setup_videos.py --check
python scripts/generate_real_pipeline_evidence.py
python scripts/validate_submission.py
```

