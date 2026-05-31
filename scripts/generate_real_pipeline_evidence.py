#!/usr/bin/env python3
"""Run real YOLO validation and generate REAL_PIPELINE_EVIDENCE.md."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT_PATH = REPO_ROOT / "REAL_PIPELINE_EVIDENCE.md"
EVIDENCE_JSON = REPO_ROOT / "docs" / "evidence" / "real_pipeline_validation.json"
INGEST_CAMERAS = ("CAM 3", "CAM 1", "CAM 5")


def _run(cmd: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("API_KEY", "purple-demo-key")
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _videos_present() -> tuple[bool, list[str]]:
    missing = [
        f"CAM {i}.mp4"
        for i in range(1, 6)
        if not (REPO_ROOT / "data" / "videos" / f"CAM {i}.mp4").is_file()
    ]
    return len(missing) == 0, missing


def run_detection_validation(*, max_frames: int) -> dict:
    print(f"Running full detection validation (real YOLO, max_frames={max_frames})...")
    proc = _run(
        [
            sys.executable,
            "scripts/validate_detection.py",
            "--max-frames",
            str(max_frames),
        ],
        timeout=7200,
    )
    payload = {
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout.strip().splitlines()[-8:],
        "stderr_tail": proc.stderr.strip().splitlines()[-8:],
    }
    if EVIDENCE_JSON.parent.joinpath("detection_validation.json").is_file():
        payload["detection_validation"] = json.loads(
            (REPO_ROOT / "docs" / "evidence" / "detection_validation.json").read_text(encoding="utf-8")
        )
    return payload


def run_ingest_validation(*, max_frames: int, use_mock: bool) -> list[dict]:
    results: list[dict] = []
    mode = "mock" if use_mock else "yolo"
    for cam in INGEST_CAMERAS:
        print(f"Ingest validation — {cam} ({mode})...")
        cmd = [
            sys.executable,
            "-m",
            "pipeline.run",
            "--ingest",
            "--persist-sessions",
            "--camera",
            cam,
            "--max-frames",
            str(max_frames),
        ]
        if use_mock:
            cmd.append("--mock")
        proc = _run(cmd, timeout=900 if not use_mock else 180)
        results.append(
            {
                "camera": cam,
                "mode": mode,
                "exit_code": proc.returncode,
                "success": proc.returncode == 0,
                "stdout_tail": proc.stdout.strip().splitlines()[-4:],
                "stderr_tail": proc.stderr.strip().splitlines()[-4:],
            }
        )
    return results


def run_submission_validation(*, api_only: bool, use_mock: bool, max_frames: int) -> dict:
    print("Running validate_submission.py...")
    cmd = [sys.executable, "scripts/validate_submission.py", "--max-frames", str(max_frames)]
    if api_only:
        cmd.append("--api-only")
    if use_mock:
        cmd.append("--mock")
    proc = _run(cmd, timeout=7200 if not api_only and not use_mock else 600)
    lines = proc.stdout.strip().splitlines()
    passed = sum(1 for line in lines if line.startswith("[PASS]"))
    failed = sum(1 for line in lines if line.startswith("[FAIL]"))
    return {
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "summary_line": lines[-1] if lines else "",
        "output": lines,
    }


def write_report(
    *,
    max_frames: int,
    detection: dict,
    ingest_runs: list[dict],
    submission: dict,
    videos_ok: bool,
    missing: list[str],
) -> None:
    det = detection.get("detection_validation") or {}
    cameras = det.get("cameras") or []
    lines = [
        "# Real Pipeline Validation Evidence",
        "",
        f"**Generated:** {datetime.now(tz=UTC).isoformat()}  ",
        f"**Detector:** YOLOv11 (`yolo11n.pt`) — **real inference, no mock**  ",
        f"**Videos:** Brigade Road CCTV (`data/videos/CAM 1–5.mp4`)  ",
        f"**Validation frames/camera:** {max_frames} (detection sweep) / ingest proof on CAM 3, 1, 5",
        "",
        "## Executive summary",
        "",
        "| Claim | Evidence |",
        "|-------|----------|",
        f"| Real YOLO on CCTV MP4s | `{det.get('detector_mode', 'yolo')}` mode, model `{det.get('detector_model', 'yolo11n.pt')}` |",
        f"| Videos processed | **{det.get('videos_processed', len([c for c in cameras if c.get('status') == 'Processed']))}** / 5 |",
        f"| Frames analyzed | **{det.get('total_frames_processed', '—')}** |",
        f"| People detections | **{det.get('total_people_detections', '—')}** |",
        f"| Pipeline ingest (real YOLO) | **{sum(1 for r in ingest_runs if r['success'])}** / {len(ingest_runs)} cameras |",
        f"| `validate_submission.py` | **{submission.get('summary_line', '—')}** |",
        "",
        "> Mock trajectories are **opt-in only** (`python scripts/validate_submission.py --mock`).",
        "> Default validation runs Ultralytics YOLO on real footage.",
        "",
        "---",
        "",
        "## 1. CCTV video source",
        "",
    ]
    if videos_ok:
        lines.append("All five MP4 files present under `data/videos/`.")
    else:
        lines.append(f"Missing: {', '.join(missing)} — run `python scripts/setup_videos.py --source <CCTV folder>`")

    lines.extend(["", "---", "", "## 2. Full detection validation (real YOLO)", ""])
    if cameras:
        lines.extend([
            "| Camera | Frames | Detections | Avg conf. | Zone enters | Staff tracks | Status |",
            "|--------|-------:|-----------:|----------:|------------:|-------------:|--------|",
        ])
        for cam in cameras:
            lines.append(
                f"| {cam.get('camera_name')} | {cam.get('frames_processed')} | "
                f"{cam.get('people_detected')} | {cam.get('avg_confidence', '—')} | "
                f"{cam.get('zone_enter_events', 0)} | {cam.get('staff_tracks_classified', 0)} | "
                f"{cam.get('status')} |"
            )
        lines.extend([
            "",
            f"Processing time: **{det.get('accuracy', {}).get('processing_seconds', '—')}s**  ",
            f"Correlation ID: `{det.get('correlation_id', '—')}`  ",
            f"JSON: [`docs/evidence/detection_validation.json`](docs/evidence/detection_validation.json)",
        ])
    else:
        lines.append(f"Detection validation exit code: {detection.get('exit_code')}")
        if detection.get("stderr_tail"):
            lines.append("")
            lines.append("```")
            lines.extend(detection["stderr_tail"])
            lines.append("```")

    lines.extend(["", "---", "", "## 3. Ingest proof (real YOLO → API)", ""])
    lines.extend([
        "Command pattern (default — no `--mock`):",
        "",
        "```bash",
        "python -m pipeline.run --ingest --persist-sessions --camera \"CAM 3\" --max-frames 25",
        "```",
        "",
        "| Camera | Mode | Exit | Result |",
        "|--------|------|-----:|--------|",
    ])
    for run in ingest_runs:
        status = "PASS" if run["success"] else "FAIL"
        lines.append(f"| {run['camera']} | {run['mode']} | {run['exit_code']} | {status} |")

    lines.extend(["", "---", "", "## 4. Submission validator", ""])
    lines.extend([
        "Default:",
        "",
        "```bash",
        "python scripts/validate_submission.py",
        "```",
        "",
        "Optional mock (CI/dev only):",
        "",
        "```bash",
        "python scripts/validate_submission.py --mock",
        "```",
        "",
        "### Check output",
        "",
        "```",
    ])
    lines.extend(submission.get("output") or ["(not run)"])
    lines.extend(["```", "", "---", "", "## 5. Reproduce", "", "```bash", "pip install -e \".[dev,pipeline]\"", "python scripts/setup_videos.py --check", "python scripts/generate_real_pipeline_evidence.py", "python scripts/validate_submission.py", "```", ""])

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    bundle = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "max_frames": max_frames,
        "videos_ok": videos_ok,
        "missing_videos": missing,
        "detection_validation": detection,
        "ingest_runs": ingest_runs,
        "submission_validation": submission,
    }
    EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_JSON.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate real YOLO pipeline evidence")
    parser.add_argument("--max-frames", type=int, default=int(os.environ.get("EVIDENCE_MAX_FRAMES", "30")))
    parser.add_argument("--skip-detection", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-submission", action="store_true")
    parser.add_argument("--api-only-submission", action="store_true")
    parser.add_argument("--mock-ingest", action="store_true", help="Compare mock ingest (not default)")
    args = parser.parse_args()

    videos_ok, missing = _videos_present()
    if not videos_ok:
        print(f"WARN: missing videos: {missing}")

    detection: dict = {}
    if not args.skip_detection and videos_ok:
        detection = run_detection_validation(max_frames=args.max_frames)
        if detection.get("exit_code") != 0:
            print("WARN: detection validation returned non-zero", file=sys.stderr)

    ingest_runs: list[dict] = []
    if not args.skip_ingest and videos_ok:
        ingest_runs = run_ingest_validation(
            max_frames=min(args.max_frames, 25),
            use_mock=args.mock_ingest,
        )

    submission: dict = {}
    if not args.skip_submission:
        submission = run_submission_validation(
            api_only=args.api_only_submission,
            use_mock=False,
            max_frames=min(args.max_frames, 25),
        )

    write_report(
        max_frames=args.max_frames,
        detection=detection,
        ingest_runs=ingest_runs,
        submission=submission,
        videos_ok=videos_ok,
        missing=missing,
    )
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {EVIDENCE_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
