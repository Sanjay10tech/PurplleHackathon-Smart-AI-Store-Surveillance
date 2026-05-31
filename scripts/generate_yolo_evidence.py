"""Generate YOLO detection evidence on real CCTV footage for Purple submission."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"
VIDEO = REPO_ROOT / "data" / "videos" / "CAM 3.mp4"


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    if not VIDEO.is_file():
        print(f"SKIP: video not found at {VIDEO}")
        print("Run: python scripts/setup_videos.py --source <CCTV folder>")
        sys.exit(0)

    cmd = [
        sys.executable,
        "-m",
        "pipeline.run",
        "--camera",
        "CAM 3",
        "--max-frames",
        "25",
        "--write-samples",
    ]
    print("Running real YOLO detection (no --mock)...")
    started = datetime.now(tz=UTC)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    elapsed = (datetime.now(tz=UTC) - started).total_seconds()

    samples_dir = REPO_ROOT / "data" / "samples" / "events"
    sample_files = sorted(samples_dir.glob("*.json")) if samples_dir.is_dir() else []

    report = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "mode": "yolo_real",
        "camera": "CAM 3",
        "video": str(VIDEO),
        "max_frames": 25,
        "duration_seconds": round(elapsed, 2),
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout.strip().splitlines()[-5:],
        "stderr_tail": proc.stderr.strip().splitlines()[-5:],
        "sample_event_files": [str(p.relative_to(REPO_ROOT)) for p in sample_files[-5:]],
        "success": proc.returncode == 0,
    }

    out = EVIDENCE_DIR / "yolo_evidence.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Evidence written to {out}")
    if proc.returncode != 0:
        print(proc.stderr[-500:])
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
