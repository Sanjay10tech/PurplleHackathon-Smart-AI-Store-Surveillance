"""Discover CCTV MP4 files and map them to configured pipeline cameras."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import REPO_ROOT, CameraConfig

DEFAULT_VIDEO_ROOT = REPO_ROOT / "data" / "videos"


@dataclass(frozen=True)
class VideoTarget:
    video_path: Path
    camera: CameraConfig


def normalize_video_key(name: str) -> str:
    """Normalize ``CAM 1.mp4`` / ``cam_1`` / ``CAM1`` to a comparable token."""
    stem = Path(name).stem
    return re.sub(r"[\s_\-.]+", "", stem.lower())


def discover_mp4_files(root: Path) -> list[Path]:
    """Recursively find all ``.mp4`` files under *root*."""
    if not root.is_dir():
        return []
    return sorted(p.resolve() for p in root.rglob("*.mp4") if p.is_file())


def match_video_to_camera(video: Path, cameras: list[CameraConfig]) -> CameraConfig | None:
    key = normalize_video_key(video.name)
    for cam in cameras:
        if normalize_video_key(cam.name) == key:
            return cam
        if normalize_video_key(Path(cam.video).name) == key:
            return cam
    return None


def build_video_targets(
    cameras: list[CameraConfig],
    *,
    video_root: Path | None = None,
) -> tuple[list[VideoTarget], list[Path]]:
    """
    Map discovered MP4 files to pipeline cameras.

    Returns (matched targets, unmatched video paths).
    When multiple files map to the same camera, the first discovery wins.
    """
    root = (video_root or DEFAULT_VIDEO_ROOT).resolve()
    discovered = discover_mp4_files(root)
    targets: list[VideoTarget] = []
    unmatched: list[Path] = []
    seen_camera_ids: set[str] = set()

    for video in discovered:
        cam = match_video_to_camera(video, cameras)
        if cam is None:
            unmatched.append(video)
            continue
        if cam.id in seen_camera_ids:
            continue
        seen_camera_ids.add(cam.id)
        targets.append(VideoTarget(video_path=video, camera=cam))

    return targets, unmatched
