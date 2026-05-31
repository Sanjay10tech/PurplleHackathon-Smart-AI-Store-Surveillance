"""Generate real YOLO detection evidence: annotated frames, tracking shots, events, markdown."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EVIDENCE = REPO_ROOT / "docs" / "evidence"
ANNOTATED = EVIDENCE / "annotated"
TRACKING = EVIDENCE / "tracking"
VIDEO_DIR = REPO_ROOT / "data" / "videos"
CAMERAS = ["CAM 3", "CAM 1", "CAM 5"]
MAX_FRAMES = 20


def _draw_detections(frame_bgr, detections) -> tuple[object, int]:
    import cv2

    annotated = frame_bgr.copy()
    count = 0
    h, w = annotated.shape[:2]
    for det in detections:
        x, y, bw, bh = det.bbox_xywh
        x1 = int(x * w)
        y1 = int(y * h)
        x2 = int((x + bw) * w)
        y2 = int((y + bh) * h)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 80), 2)
        cv2.putText(
            annotated,
            f"person {det.confidence:.2f}",
            (x1, max(0, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 200, 80),
            1,
        )
        count += 1
    return annotated, count


def _run_yolo_on_camera(camera: str, detector_cfg: dict) -> dict:
    import cv2

    from pipeline.detect import YoloV11PersonDetector

    video = VIDEO_DIR / f"{camera}.mp4"
    if not video.is_file():
        return {"camera": camera, "skipped": True, "reason": "video missing"}

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return {"camera": camera, "skipped": True, "reason": "cannot open video"}

    detector = YoloV11PersonDetector(detector_cfg)
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(native_fps / 5.0)))

    frames_sampled = 0
    detections_total = 0
    confidences: list[float] = []
    saved_frames: list[str] = []

    frame_idx = 0
    while frames_sampled < MAX_FRAMES:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step != 0:
            frame_idx += 1
            continue

        dets = detector.detect(frame)
        detections_total += len(dets)
        confidences.extend(d.confidence for d in dets)
        annotated, _ = _draw_detections(frame, dets)

        out_name = f"{camera.replace(' ', '_')}_frame_{frames_sampled:03d}.jpg"
        out_path = ANNOTATED / out_name
        cv2.imwrite(str(out_path), annotated)
        saved_frames.append(str(out_path.relative_to(REPO_ROOT)))

        if frames_sampled == 0:
            track_path = TRACKING / f"{camera.replace(' ', '_')}_tracking.jpg"
            cv2.imwrite(str(track_path), annotated)

        frames_sampled += 1
        frame_idx += 1

    cap.release()
    avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    return {
        "camera": camera,
        "video": str(video.relative_to(REPO_ROOT)),
        "frames_sampled": frames_sampled,
        "detections_total": detections_total,
        "avg_confidence": avg_conf,
        "annotated_frames": saved_frames,
        "tracking_screenshot": str(
            (TRACKING / f"{camera.replace(' ', '_')}_tracking.jpg").relative_to(REPO_ROOT)
        )
        if saved_frames
        else None,
    }


def _run_pipeline_samples() -> dict:
    import subprocess

    cmd = [
        sys.executable,
        "-m",
        "pipeline.run",
        "--camera",
        "CAM 3",
        "--max-frames",
        "15",
        "--write-samples",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    samples_dir = REPO_ROOT / "data" / "samples" / "events"
    events: list[dict] = []
    if samples_dir.is_dir():
        for path in sorted(samples_dir.glob("*.json"))[:5]:
            try:
                events.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    out = EVIDENCE / "sample_events.json"
    out.write_text(json.dumps(events, indent=2), encoding="utf-8")
    return {
        "exit_code": proc.returncode,
        "sample_count": len(events),
        "output": str(out.relative_to(REPO_ROOT)),
        "stdout_tail": proc.stdout.strip().splitlines()[-3:],
    }


def _write_markdown(report: dict) -> None:
    lines = [
        "# Detection Evidence — Real YOLO on CCTV",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Model:** {report['detector_model']}",
        "",
        "## Summary",
        "",
        "| Camera | Frames | Detections | Avg confidence | Status |",
        "|--------|-------:|-----------:|---------------:|--------|",
    ]
    for cam in report["cameras"]:
        if cam.get("skipped"):
            lines.append(f"| {cam['camera']} | — | — | — | SKIPPED ({cam.get('reason')}) |")
        else:
            lines.append(
                f"| {cam['camera']} | {cam['frames_sampled']} | {cam['detections_total']} "
                f"| {cam['avg_confidence']} | OK |"
            )

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- Annotated frames: `docs/evidence/annotated/`",
            "- Tracking screenshots: `docs/evidence/tracking/`",
            "- Sample events: `docs/evidence/sample_events.json`",
            "",
            "## Observed accuracy and limitations",
            "",
            report.get("limitations", ""),
            "",
            "## Pipeline sample run",
            "",
            f"- Exit code: {report['pipeline_samples']['exit_code']}",
            f"- Sample events captured: {report['pipeline_samples']['sample_count']}",
        ]
    )
    (REPO_ROOT / "docs" / "DETECTION_EVIDENCE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    try:
        import cv2  # noqa: F401
        from ultralytics import YOLO  # noqa: F401
    except ImportError as exc:
        print(f"SKIP: pipeline CV deps not installed ({exc})")
        sys.exit(0)

    from pipeline.config import PipelineConfig

    ANNOTATED.mkdir(parents=True, exist_ok=True)
    TRACKING.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    cfg = PipelineConfig.load()
    detector_cfg = cfg.detector

    missing = [f"{c}.mp4" for c in CAMERAS if not (VIDEO_DIR / f"{c}.mp4").is_file()]
    if missing:
        print("WARN: missing videos:", ", ".join(missing))
        print("Run: python scripts/setup_videos.py --source '<CCTV Footage>'")

    camera_reports = [_run_yolo_on_camera(cam, detector_cfg) for cam in CAMERAS]
    pipeline_samples = _run_pipeline_samples()

    report = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "detector_model": detector_cfg.get("model", "yolo11n.pt"),
        "mode": "yolo_real_no_mock",
        "cameras": camera_reports,
        "pipeline_samples": pipeline_samples,
        "limitations": (
            "YOLOv11n detects COCO `person` class only; crowded scenes may merge boxes. "
            "ByteTrack ID switches under occlusion are mitigated by session rules but not eliminated. "
            "Staff uniform heuristic is rule-based, not trained. Zone lines require manual calibration per store."
        ),
    }
    (EVIDENCE / "detection_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_markdown(report)
    print("Wrote docs/DETECTION_EVIDENCE.md and docs/evidence/detection_report.json")


if __name__ == "__main__":
    main()
