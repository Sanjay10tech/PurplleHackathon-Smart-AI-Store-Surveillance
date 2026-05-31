"""One-off CCTV dataset analysis — metadata, motion, traffic heuristics."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

DATASET = Path(
    r"C:\Users\DELL\Downloads\CCTV Footage-20260529T160731Z-3-00144614ea\CCTV Footage"
)
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "analysis_frames"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def analyze_video(path: Path, cam_id: str) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {"camera": cam_id, "error": "cannot open"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total_frames / fps if fps > 0 else 0

    # Sample every N seconds for motion + occupancy
    sample_interval_s = max(1.0, duration_s / 60)  # ~60 samples max
    sample_frames_idx = [
        int(min(total_frames - 1, t * fps)) for t in np.arange(0, duration_s, sample_interval_s)
    ]

    prev_gray = None
    motion_by_region: dict[str, list[float]] = {
        "top": [],
        "middle": [],
        "bottom": [],
        "left": [],
        "right": [],
    }
    person_counts: list[int] = []
    motion_totals: list[float] = []

    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    saved_samples: list[str] = []
    sample_positions = [0.05, 0.25, 0.5, 0.75, 0.95]

    for idx in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break

        t_ratio = idx / max(total_frames - 1, 1)
        if any(abs(t_ratio - p) < (1.0 / max(total_frames, 1)) for p in sample_positions):
            out_name = f"{cam_id.replace(' ', '_')}_t{int(t_ratio * 100):03d}.jpg"
            out_path = OUT_DIR / out_name
            cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            saved_samples.append(out_name)

        if idx not in sample_frames_idx:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if prev_gray is not None:
            diff = cv2.absdiff(prev_gray, gray)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            h, w = thresh.shape
            regions = {
                "top": thresh[0 : h // 3, :],
                "middle": thresh[h // 3 : 2 * h // 3, :],
                "bottom": thresh[2 * h // 3 :, :],
                "left": thresh[:, 0 : w // 3],
                "right": thresh[:, 2 * w // 3 :],
            }
            for name, region in regions.items():
                motion_by_region[name].append(float(np.mean(region) / 255.0))
            motion_totals.append(float(np.mean(thresh) / 255.0))

        prev_gray = gray

        # HOG person detection (downscale for speed)
        scale = 640 / max(width, height)
        if scale < 1.0:
            small = cv2.resize(frame, (int(width * scale), int(height * scale)))
        else:
            small = frame
        rects, _ = hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
        person_counts.append(len(rects))

    cap.release()

    avg_motion = float(np.mean(motion_totals)) if motion_totals else 0.0
    avg_persons = float(np.mean(person_counts)) if person_counts else 0.0
    max_persons = int(max(person_counts)) if person_counts else 0
    p95_persons = float(np.percentile(person_counts, 95)) if person_counts else 0.0

    region_motion = {k: float(np.mean(v)) if v else 0.0 for k, v in motion_by_region.items()}

    # Heuristic traffic level
    if avg_persons >= 8 or p95_persons >= 15:
        traffic = "HIGH"
    elif avg_persons >= 3 or p95_persons >= 6:
        traffic = "MEDIUM"
    elif avg_persons >= 0.5 or avg_motion > 0.015:
        traffic = "LOW"
    else:
        traffic = "VERY_LOW"

    # Entry/exit line heuristics from motion concentration at edges
    edge_scores = {
        "entry_candidate_bottom": region_motion["bottom"],
        "entry_candidate_top": region_motion["top"],
        "exit_candidate_left": region_motion["left"],
        "exit_candidate_right": region_motion["right"],
    }
    sorted_edges = sorted(edge_scores.items(), key=lambda x: x[1], reverse=True)

    return {
        "camera": cam_id,
        "file": path.name,
        "width": width,
        "height": height,
        "fps": round(fps, 2),
        "duration_s": round(duration_s, 1),
        "duration_min": round(duration_s / 60, 1),
        "total_frames": total_frames,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 1),
        "traffic_level": traffic,
        "avg_persons_hog": round(avg_persons, 2),
        "p95_persons_hog": round(p95_persons, 2),
        "max_persons_hog": max_persons,
        "avg_motion": round(avg_motion, 4),
        "region_motion": {k: round(v, 4) for k, v in region_motion.items()},
        "dominant_motion_edges": sorted_edges[:3],
        "sample_frames": saved_samples,
    }


def main() -> None:
    results = []
    for i in range(1, 6):
        path = DATASET / f"CAM {i}.mp4"
        if path.exists():
            print(f"Analyzing {path.name}...", flush=True)
            results.append(analyze_video(path, f"CAM {i}"))
        else:
            results.append({"camera": f"CAM {i}", "error": "file not found"})

    out_json = Path(__file__).resolve().parent.parent / "data" / "cctv_analysis_raw.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
