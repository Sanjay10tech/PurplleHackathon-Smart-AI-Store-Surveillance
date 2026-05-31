"""Docker pipeline worker — ingest all discovered CCTV videos after API is healthy."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REQUIRED_VIDEOS = tuple(f"CAM {i}.mp4" for i in range(1, 6))


def wait_for_api(base: str, attempts: int = 60) -> None:
    health = f"{base.rstrip('/')}/health"
    for i in range(attempts):
        try:
            with urllib.request.urlopen(health, timeout=5) as resp:
                if resp.status == 200:
                    print(f"[pipeline-worker] API healthy after {i + 1} attempt(s)")
                    return
        except Exception as exc:
            print(f"[pipeline-worker] waiting for API ({i + 1}/{attempts}): {exc}")
        time.sleep(2)
    raise SystemExit("[pipeline-worker] API did not become healthy in time")


def _videos_present(video_root: Path) -> list[Path]:
    return [video_root / name for name in REQUIRED_VIDEOS if (video_root / name).is_file()]


def main() -> None:
    api_base = os.environ.get("PIPELINE_API_BASE", "http://api:8000")
    mode = os.environ.get("PIPELINE_MODE", "yolo").lower()
    max_frames = os.environ.get("PIPELINE_MAX_FRAMES", "50")
    all_videos = os.environ.get("PIPELINE_ALL_VIDEOS", "1").strip().lower() in ("1", "true", "yes")
    video_root = Path(os.environ.get("PIPELINE_VIDEO_ROOT", "data/videos"))
    cameras = [
        c.strip()
        for c in os.environ.get(
            "PIPELINE_CAMERAS",
            "CAM 1,CAM 2,CAM 3,CAM 4,CAM 5",
        ).split(",")
        if c.strip()
    ]

    if mode == "mock":
        print("[pipeline-worker] WARN: mock mode is disabled for reviewer flow; forcing yolo")
        mode = "yolo"
    if mode != "yolo":
        raise SystemExit(f"Unknown PIPELINE_MODE={mode}")

    present = _videos_present(video_root)
    if len(present) < len(REQUIRED_VIDEOS):
        missing = [name for name in REQUIRED_VIDEOS if not (video_root / name).is_file()]
        print(
            "[pipeline-worker] skipping YOLO ingest — videos missing: "
            + ", ".join(missing)
            + " (API bootstrap JSONL supplies demo metrics)",
            flush=True,
        )
        return

    wait_for_api(api_base)

    args_base = [
        sys.executable,
        "-m",
        "pipeline.run",
        "--ingest",
        "--persist-sessions",
        "--max-frames",
        max_frames,
    ]

    if all_videos:
        cmd = [*args_base, "--all-videos"]
        print(f"[pipeline-worker] running real YOLO: {' '.join(cmd)}", flush=True)
        subprocess.run(cmd, check=True)
    else:
        for camera in cameras:
            cmd = [*args_base, "--camera", camera]
            print(f"[pipeline-worker] running real YOLO: {' '.join(cmd)}", flush=True)
            subprocess.run(cmd, check=True)

    print("[pipeline-worker] completed all cameras", flush=True)


if __name__ == "__main__":
    main()
