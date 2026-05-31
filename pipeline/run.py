"""Run detection pipeline and optionally ingest into the FastAPI API."""

from __future__ import annotations

import argparse
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from pipeline.config import REPO_ROOT, CameraConfig, PipelineConfig
from pipeline.detect import build_detectors_for_cameras
from pipeline.emit import EventBuilder, EventEmitter
from pipeline.report import ProcessingRunReport, VideoRunStats, write_processing_report
from pipeline.tracker import MultiCameraPipeline
from pipeline.videos import DEFAULT_VIDEO_ROOT, build_video_targets


@dataclass
class ProcessingRunResult:
    report: ProcessingRunReport
    flush_summary: dict[str, object]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Store Intelligence CCTV detection pipeline")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    parser.add_argument("--zones", type=Path, default=None, help="Path to zones.yaml")
    parser.add_argument("--mock", action="store_true", help="Use mock detector (no GPU)")
    parser.add_argument(
        "--all-videos",
        action="store_true",
        help="Discover and process all .mp4 files under --video-root (default when no --camera)",
    )
    parser.add_argument(
        "--video-root",
        type=Path,
        default=None,
        help=f"Root directory for recursive MP4 discovery (default: {DEFAULT_VIDEO_ROOT})",
    )
    parser.add_argument("--ingest", action="store_true", help="POST events to FastAPI ingest API")
    parser.add_argument(
        "--persist-sessions",
        action="store_true",
        help="Persist visitor sessions to DATABASE_URL before ingest",
    )
    parser.add_argument(
        "--write-samples",
        action="store_true",
        help="Write sample event JSON files to data/samples/events/",
    )
    parser.add_argument("--camera", type=str, default=None, help="Process single camera id or name")
    parser.add_argument("--max-frames", type=int, default=0, help="Limit frames per camera (0=all)")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write markdown processing report to this path",
    )
    return parser.parse_args(argv)


def _video_start_time(*, native_fps: float, frame_count: float, max_frames: int, sample_fps: float) -> datetime:
    """
    Anchor clip timestamps so the last sampled frame is near UTC now.

    Ensures ingested events fall inside BI query windows and /health feed checks.
    """
    step = max(1, int(round(native_fps / max(sample_fps, 0.1))))
    sampled_total = frame_count / step if frame_count > 0 else 60.0
    if max_frames:
        sampled_total = min(sampled_total, max_frames)
    clip_seconds = sampled_total / max(sample_fps, 0.1)
    return datetime.now(tz=UTC) - timedelta(seconds=clip_seconds + 5.0)


def process_camera_video(
    *,
    video_path: Path,
    camera_id: str,
    pipeline: MultiCameraPipeline,
    builder: EventBuilder,
    emitter: EventEmitter,
    sample_fps: float,
    emit_every_n: int,
    max_frames: int,
) -> int:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    step = max(1, int(round(native_fps / max(sample_fps, 0.1))))
    start_time = _video_start_time(
        native_fps=native_fps,
        frame_count=float(frame_count),
        max_frames=max_frames,
        sample_fps=sample_fps,
    )
    cam_pipeline = pipeline.pipeline_for(camera_id)

    frame_idx = 0
    sampled = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step != 0:
            frame_idx += 1
            continue

        ts = start_time + timedelta(seconds=frame_idx / native_fps)
        t0 = time.perf_counter()
        result = cam_pipeline.process_frame(frame, frame_index=frame_idx, frame_timestamp=ts)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        if sampled % emit_every_n == 0:
            emitter.add(
                builder.frame_processed(
                    result,
                    processing_ms=elapsed_ms,
                    source_video=str(video_path),
                )
            )

        for track, transition in result.zone_transitions:
            emitter.add(builder.zone_event(track, transition, occurred_at=ts))

        for ended in result.ended_tracks:
            emitter.add(builder.track_ended(ended, occurred_at=ts))

        sampled += 1
        frame_idx += 1
        if max_frames and sampled >= max_frames:
            break

    cap.release()
    return sampled


def process_synthetic_frames(
    *,
    camera_id: str,
    pipeline: MultiCameraPipeline,
    builder: EventBuilder,
    emitter: EventEmitter,
    frame_count: int,
    frame_shape: tuple[int, int, int] = (1080, 1920, 3),
    start_time: datetime | None = None,
    emit_every_n: int = 1,
) -> None:
    """Process blank frames — used when detector drives motion (trajectory mock)."""
    cam_pipeline = pipeline.pipeline_for(camera_id)
    anchor = start_time or datetime.now(tz=UTC)
    frame = np.zeros(frame_shape, dtype=np.uint8)

    for i in range(frame_count):
        ts = anchor + timedelta(seconds=i)
        t0 = time.perf_counter()
        result = cam_pipeline.process_frame(frame, frame_index=i, frame_timestamp=ts)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        if i % emit_every_n == 0:
            emitter.add(builder.frame_processed(result, processing_ms=elapsed_ms))

        for track, transition in result.zone_transitions:
            emitter.add(builder.zone_event(track, transition, occurred_at=ts))

        for ended in result.ended_tracks:
            emitter.add(builder.track_ended(ended, occurred_at=ts))


def _events_for_camera(events: list[dict], camera_id: str, *, since: int = 0) -> int:
    count = 0
    for event in events[since:]:
        payload = event.get("payload") or {}
        if payload.get("camera_id") == camera_id:
            count += 1
    return count


def _resolve_processing_queue(
    cfg: PipelineConfig,
    *,
    camera_filter: str | None,
    all_videos: bool,
    video_root: Path | None,
) -> tuple[list[tuple[CameraConfig, Path]], list[Path]]:
    if camera_filter:
        cameras = [c for c in cfg.cameras if c.id == camera_filter or c.name == camera_filter]
        if not cameras:
            raise SystemExit(f"Camera not found: {camera_filter}")
        queue: list[tuple[CameraConfig, Path]] = []
        for cam in cameras:
            video = Path(cam.video)
            if video.exists():
                queue.append((cam, video))
            else:
                print(f"Skipping missing video for {cam.name}: {video}")
        return queue, []

    root = (video_root or DEFAULT_VIDEO_ROOT).resolve()
    if all_videos or root.is_dir():
        targets, unmatched = build_video_targets(cfg.cameras, video_root=root)
        if targets:
            return [(t.camera, t.video_path) for t in targets], unmatched

    queue = []
    for cam in cfg.cameras:
        video = Path(cam.video)
        if video.exists():
            queue.append((cam, video))
        else:
            print(f"Skipping missing video for {cam.name}: {video}")
    return queue, []


def _ingest_summary(flush_summary: dict[str, object]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for key in ("event_count", "session_count", "sessions_persisted"):
        value = flush_summary.get(key)
        if isinstance(value, int):
            summary[key] = value
    api = flush_summary.get("api")
    if isinstance(api, dict):
        for key in ("accepted", "rejected", "duplicate", "posted", "batches"):
            value = api.get(key)
            if isinstance(value, int):
                summary[key] = value
    return summary


def run_pipeline(args: argparse.Namespace | None = None) -> ProcessingRunResult:
    args = args or _parse_args()
    cfg = PipelineConfig.load(args.config, args.zones)

    use_discovery = args.all_videos or (args.camera is None and not args.write_samples)

    if args.mock:
        cfg.detector["mode"] = "mock"
    else:
        cfg.detector["mode"] = "yolo"

    if args.ingest:
        cfg.emit["post_to_api"] = True
    if args.persist_sessions:
        cfg.emit["persist_sessions"] = True

    if args.write_samples:
        paths = EventEmitter.write_sample_files()
        print("Sample event files written:")
        for name, path in paths.items():
            print(f"  {name}: {path}")
        if not args.camera and not args.ingest and not use_discovery:
            empty_report = ProcessingRunReport(
                generated_at=datetime.now(tz=UTC),
                detector_mode=str(cfg.detector.get("mode", "yolo")),
                correlation_id="samples-only",
                video_stats=[],
                ingest_summary={},
                total_visitors=0,
                unmatched_videos=[],
            )
            return ProcessingRunResult(report=empty_report, flush_summary={})

    queue, unmatched = _resolve_processing_queue(
        cfg,
        camera_filter=args.camera,
        all_videos=use_discovery,
        video_root=args.video_root,
    )
    if not queue:
        raise SystemExit("No CCTV videos found to process. Place MP4 files under data/videos/.")

    detector = build_detectors_for_cameras(cfg.detector, cfg.cameras)
    multi = MultiCameraPipeline(cfg, detector)

    run_id = uuid.uuid4()
    correlation_id = f"pipeline-{run_id.hex[:12]}"
    builder = EventBuilder(
        store_id=cfg.store_id,
        tenant_id=cfg.tenant_id,
        schema_version=cfg.schema_version,
        pipeline_run_id=run_id,
        correlation_id=correlation_id,
        detector_mode=str(cfg.detector.get("mode", "yolo")),
    )
    emitter = EventEmitter(cfg.emit, store_id=cfg.store_id, tenant_id=cfg.tenant_id)

    sample_fps = float(cfg.processing.get("sample_fps", 5.0))
    emit_every_n = int(cfg.processing.get("emit_frame_events_every_n", 30))

    video_stats: list[VideoRunStats] = []
    for cam, video in queue:
        event_offset = len(emitter.events)
        print(f"Processing {cam.name} ({cam.id}) — {video}", flush=True)
        try:
            frames = process_camera_video(
                video_path=video,
                camera_id=cam.id,
                pipeline=multi,
                builder=builder,
                emitter=emitter,
                sample_fps=sample_fps,
                emit_every_n=emit_every_n,
                max_frames=args.max_frames,
            )
            events = _events_for_camera(emitter.events, cam.id, since=event_offset)
            video_stats.append(
                VideoRunStats(
                    video_name=video.name,
                    camera_name=cam.name,
                    frames_processed=frames,
                    events_generated=events,
                    status="Processed",
                )
            )
        except Exception as exc:
            video_stats.append(
                VideoRunStats(
                    video_name=video.name,
                    camera_name=cam.name,
                    frames_processed=0,
                    events_generated=0,
                    status=f"Failed: {exc}",
                )
            )
            print(f"  ERROR: {exc}")

    sessions = multi.sessions.sessions
    flush_summary = emitter.flush(sessions, batch_size=int(cfg.processing.get("batch_size", 100)))
    total_visitors = len(multi.sessions.distinct_visitor_ids())

    report = ProcessingRunReport(
        generated_at=datetime.now(tz=UTC),
        detector_mode=str(cfg.detector.get("mode", "yolo")),
        correlation_id=correlation_id,
        video_stats=video_stats,
        ingest_summary=_ingest_summary(flush_summary),
        total_visitors=total_visitors,
        unmatched_videos=[p.name for p in unmatched],
    )

    report_path = args.report or (
        REPO_ROOT / "docs" / "full_video_processing_report.md" if use_discovery and args.ingest else None
    )
    if report_path is not None:
        written = write_processing_report(report, report_path)
        print(f"Processing report: {written}")

    print("Pipeline complete:")
    print(f"  videos_processed: {report.total_videos_processed}")
    print(f"  frames_analyzed: {report.total_frames_analyzed}")
    print(f"  events_generated: {report.total_events_generated}")
    print(f"  visitors_detected: {report.total_visitors}")
    for key, value in flush_summary.items():
        if key not in ("events_path", "sessions_path"):
            print(f"  {key}: {value}")

    return ProcessingRunResult(report=report, flush_summary=flush_summary)


def main() -> None:
    run_pipeline()


if __name__ == "__main__":
    main()
