#!/usr/bin/env python3
"""Sweep YOLO conf/IoU on Purplle CCTV clips and recommend detector settings."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.config import PipelineConfig, resolve_video_path

# Weak priors from HOG analysis (data/cctv_analysis_raw.json).
CAMERA_PRIORS: dict[str, dict[str, float]] = {
    "CAM 1": {"max_persons": 1, "p95_persons": 0.05, "crowd": 0.0},
    "CAM 2": {"max_persons": 2, "p95_persons": 1.0, "crowd": 0.4},
    "CAM 3": {"max_persons": 1, "p95_persons": 1.0, "crowd": 0.0},
    "CAM 4": {"max_persons": 1, "p95_persons": 0.0, "crowd": 0.0},
    "CAM 5": {"max_persons": 2, "p95_persons": 2.0, "crowd": 0.6},
}


@dataclass(frozen=True)
class DetectParams:
    confidence: float
    iou: float
    imgsz: int
    min_bbox_height: float
    min_bbox_area: float
    max_det: int


@dataclass
class FrameSample:
    camera: str
    frame_index: int
    hog_expect: int  # 0 or 1+ from prior sampling


def _load_samples(cfg: PipelineConfig, *, samples_per_video: int) -> list[tuple[str, Path, list[int]]]:
    bundles: list[tuple[str, Path, list[int]]] = []
    for cam in cfg.cameras:
        video = resolve_video_path(str(cam.video))
        if not video.exists():
            continue
        cap = cv2.VideoCapture(str(video))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        if total <= 0:
            continue
        positions = np.linspace(int(total * 0.05), int(total * 0.95), samples_per_video, dtype=int)
        bundles.append((cam.name, video, sorted(set(int(p) for p in positions))))
    return bundles


def _detect_frame(
    model,
    frame: np.ndarray,
    params: DetectParams,
) -> list[dict]:
    h, w = frame.shape[:2]
    result = model.predict(
        source=frame,
        conf=params.confidence,
        iou=params.iou,
        classes=[0],
        imgsz=params.imgsz,
        max_det=params.max_det,
        verbose=False,
    )[0]
    if result.boxes is None or len(result.boxes) == 0:
        return []

    out: list[dict] = []
    boxes = result.boxes.xywh.cpu().numpy()
    confs = result.boxes.conf.cpu().numpy()
    for (xc, yc, bw, bh), conf in zip(boxes, confs, strict=True):
        nw, nh = float(bw / w), float(bh / h)
        if nh < params.min_bbox_height or (nw * nh) < params.min_bbox_area:
            continue
        aspect = nh / max(nw, 1e-6)
        if aspect < 1.2 or aspect > 6.0:
            continue
        out.append(
            {
                "confidence": float(conf),
                "bbox_xywh": (
                    max(0.0, (xc - bw / 2) / w),
                    max(0.0, (yc - bh / 2) / h),
                    min(1.0, nw),
                    min(1.0, nh),
                ),
            }
        )
    return out


def _score_config(
    per_camera_counts: dict[str, list[int]],
    per_camera_confs: dict[str, list[float]],
) -> dict[str, float]:
    recall = 0.0
    precision = 0.0
    crowd = 0.0
    n = 0
    for cam, counts in per_camera_counts.items():
        prior = CAMERA_PRIORS.get(cam, {"max_persons": 2, "p95_persons": 1, "crowd": 0.3})
        expected_max = int(prior["max_persons"])
        expected_p95 = float(prior["p95_persons"])
        for count in counts:
            n += 1
            # Recall proxy: detect when scene likely has a person.
            if expected_p95 >= 0.5 and count == 0:
                recall -= 1.0
            elif expected_p95 >= 0.5 and count >= 1:
                recall += 1.0
            elif expected_p95 < 0.5 and count >= 1:
                recall += 0.5
            else:
                recall += 0.25

            # Precision proxy: penalize excess boxes in sparse cameras.
            if count <= expected_max:
                precision += 1.0
            elif count == expected_max + 1:
                precision += 0.35
            else:
                precision -= 0.5

    crowd_denom = 0
    for cam, counts in per_camera_counts.items():
        if CAMERA_PRIORS.get(cam, {}).get("crowd", 0) >= 0.5:
            crowd += sum(
                1.0 if count >= 2 else (0.5 if count == 1 else -0.5) for count in counts
            )
            crowd_denom += len(counts)
    crowd_denom = max(crowd_denom, 1)

    denom = max(n, 1)
    avg_conf = float(np.mean([c for vals in per_camera_confs.values() for c in vals])) if per_camera_confs else 0.0
    return {
        "recall_proxy": round(recall / denom, 4),
        "precision_proxy": round(precision / denom, 4),
        "crowd_proxy": round(crowd / crowd_denom, 4),
        "avg_confidence": round(avg_conf, 4),
        "frames_scored": denom,
    }


def sweep(
    *,
    legacy: bool = False,
    samples_per_video: int = 12,
    imgsz: int = 960,
) -> dict:
    from ultralytics import YOLO

    cfg = PipelineConfig.load()
    model_name = str(cfg.detector.get("model", "yolo11n.pt"))
    model = YOLO(model_name)

    conf_values = [0.28, 0.32, 0.35, 0.38, 0.42, 0.45] if not legacy else [0.45, 0.50, 0.55]
    iou_values = [0.40, 0.45, 0.50, 0.55] if not legacy else [0.50, 0.55, 0.60]
    min_h = 0.06 if legacy else 0.08
    min_area = 0.004 if legacy else 0.006

    bundles = _load_samples(cfg, samples_per_video=samples_per_video)
    results: list[dict] = []

    for conf in conf_values:
        for iou in iou_values:
            params = DetectParams(
                confidence=conf,
                iou=iou,
                imgsz=imgsz,
                min_bbox_height=min_h,
                min_bbox_area=min_area,
                max_det=12,
            )
            per_camera_counts: dict[str, list[int]] = {}
            per_camera_confs: dict[str, list[float]] = {}
            for cam_name, video_path, frame_indices in bundles:
                cap = cv2.VideoCapture(str(video_path))
                counts: list[int] = []
                confs: list[float] = []
                for target in frame_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                    ok, frame = cap.read()
                    if not ok:
                        continue
                    dets = _detect_frame(model, frame, params)
                    counts.append(len(dets))
                    confs.extend(d["confidence"] for d in dets)
                cap.release()
                per_camera_counts[cam_name] = counts
                per_camera_confs[cam_name] = confs

            scores = _score_config(per_camera_counts, per_camera_confs)
            composite = (
                0.40 * scores["recall_proxy"]
                + 0.40 * scores["precision_proxy"]
                + 0.20 * scores["crowd_proxy"]
            )
            results.append(
                {
                    "confidence": conf,
                    "iou": iou,
                    "imgsz": imgsz,
                    "min_bbox_height": min_h,
                    "min_bbox_area": min_area,
                    "composite_score": round(composite, 4),
                    **scores,
                    "per_camera_mean_counts": {
                        cam: round(float(np.mean(vals)), 2) if vals else 0.0
                        for cam, vals in per_camera_counts.items()
                    },
                }
            )

    results.sort(key=lambda r: r["composite_score"], reverse=True)
    best = results[0]
    baseline = next(
        (
            r
            for r in results
            if r["confidence"] == 0.45 and r["iou"] == 0.50 and r["imgsz"] == imgsz
        ),
        results[-1],
    )
    return {
        "mode": "legacy_baseline" if legacy else "tuned_sweep",
        "model": model_name,
        "samples_per_video": samples_per_video,
        "imgsz": imgsz,
        "best": best,
        "baseline_current_config": baseline,
        "top5": results[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune YOLO conf/IoU on CCTV dataset")
    parser.add_argument("--legacy", action="store_true", help="Evaluate current/default thresholds")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--out", type=str, default="data/yolo_tuning_results.json")
    args = parser.parse_args()

    report = sweep(legacy=args.legacy, samples_per_video=args.samples, imgsz=args.imgsz)
    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        best = report["best"]
        base = report["baseline_current_config"]
        print(f"Best: conf={best['confidence']} iou={best['iou']} score={best['composite_score']}")
        print(
            f"Baseline (0.45/0.50): score={base.get('composite_score', 'n/a')} "
            f"recall={base.get('recall_proxy')} precision={base.get('precision_proxy')}"
        )
        print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
