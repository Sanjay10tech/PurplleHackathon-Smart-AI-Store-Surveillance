#!/usr/bin/env python3
"""Process all CCTV videos with real YOLO, ingest events, and refresh dashboard metrics."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.run import _parse_args, run_pipeline  # noqa: E402


def _build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real YOLO on all CCTV videos, ingest, project metrics, write report",
    )
    parser.add_argument(
        "--video-root",
        type=Path,
        default=None,
        help="Directory to scan recursively for MP4 files (default: data/videos)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Limit sampled frames per video (0 = full clip at sample_fps)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT / "docs" / "full_video_processing_report.md",
        help="Markdown report output path",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip store_metrics projection after ingest",
    )
    script_args, _ = parser.parse_known_args(argv)

    pipeline_argv = [
        "--all-videos",
        "--ingest",
        "--persist-sessions",
        "--report",
        str(script_args.report),
    ]
    if script_args.video_root is not None:
        pipeline_argv.extend(["--video-root", str(script_args.video_root)])
    if script_args.max_frames:
        pipeline_argv.extend(["--max-frames", str(script_args.max_frames)])

    args = _parse_args(pipeline_argv)
    args.skip_metrics = script_args.skip_metrics
    return args


async def _project_metrics() -> int:
    from scripts.project_demo_metrics import project_footfall

    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql://"):
        os.environ["DATABASE_URL"] = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return await project_footfall()


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("API_KEY", "purple-demo-key")
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql://"):
        os.environ["DATABASE_URL"] = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    args = _build_args(argv)

    result = run_pipeline(args)

    if not getattr(args, "skip_metrics", False) and args.ingest:
        try:
            buckets = asyncio.run(_project_metrics())
            print(f"  metrics_buckets_projected: {buckets}")
        except Exception as exc:
            print(f"  metrics_projection_warning: {exc}")

    report = result.report
    print("\n=== Full CCTV processing summary ===")
    print(f"Total videos processed: {report.total_videos_processed}")
    print(f"Total frames analyzed: {report.total_frames_analyzed}")
    print(f"Total events generated: {report.total_events_generated}")
    print(f"Total visitors detected: {report.total_visitors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
