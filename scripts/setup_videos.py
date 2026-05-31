"""Copy or verify CCTV sample videos under data/videos/."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = REPO_ROOT / "data" / "videos"
EXPECTED = [f"CAM {i}.mp4" for i in range(1, 6)]


def check_videos() -> list[str]:
    missing = [name for name in EXPECTED if not (VIDEO_DIR / name).is_file()]
    return missing


def copy_from_source(source: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"Source directory not found: {source}")
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED:
        src = source / name
        dst = VIDEO_DIR / name
        if not src.is_file():
            print(f"  skip (missing at source): {name}")
            continue
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            print(f"  ok (already present): {name}")
            continue
        print(f"  copying {name} ...")
        shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup data/videos for the detection pipeline")
    parser.add_argument("--source", type=Path, help="Directory containing CAM 1.mp4 … CAM 5.mp4")
    parser.add_argument("--check", action="store_true", help="Only verify files exist")
    args = parser.parse_args()

    if args.check or not args.source:
        missing = check_videos()
        if missing:
            print("Missing videos in data/videos/:")
            for name in missing:
                print(f"  - {name}")
            print("\nRun: python scripts/setup_videos.py --source <CCTV Footage folder>")
            sys.exit(1)
        print(f"All {len(EXPECTED)} videos present in {VIDEO_DIR}")
        return

    print(f"Copying videos from {args.source} -> {VIDEO_DIR}")
    copy_from_source(args.source)
    missing = check_videos()
    if missing:
        print("Still missing after copy:", ", ".join(missing))
        sys.exit(1)
    print("Setup complete.")


if __name__ == "__main__":
    main()
