"""Tests for recursive CCTV video discovery and camera matching."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.config import CameraConfig
from pipeline.videos import (
    build_video_targets,
    discover_mp4_files,
    match_video_to_camera,
    normalize_video_key,
)


def _cam(name: str, cam_id: str) -> CameraConfig:
    return CameraConfig(id=cam_id, name=name, role="floor", video=f"data/videos/{name}.mp4")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CAM 1.mp4", "cam1"),
        ("cam_1.mp4", "cam1"),
        ("CAM1.MP4", "cam1"),
    ],
)
def test_normalize_video_key(raw: str, expected: str) -> None:
    assert normalize_video_key(raw) == expected


def test_discover_mp4_files_recursive(tmp_path: Path) -> None:
    nested = tmp_path / "store_a"
    nested.mkdir()
    (tmp_path / "CAM 1.mp4").write_bytes(b"x")
    (nested / "CAM 2.mp4").write_bytes(b"x")
    (tmp_path / "readme.txt").write_text("nope")

    found = discover_mp4_files(tmp_path)
    assert [p.name for p in found] == ["CAM 1.mp4", "CAM 2.mp4"]


def test_match_video_to_camera() -> None:
    cameras = [_cam("CAM 3", "id-3"), _cam("CAM 1", "id-1")]
    video = Path("data/videos/CAM 3.mp4")
    matched = match_video_to_camera(video, cameras)
    assert matched is not None
    assert matched.id == "id-3"


def test_build_video_targets_dedupes_camera(tmp_path: Path) -> None:
    (tmp_path / "CAM 1.mp4").write_bytes(b"a")
    (tmp_path / "dup").mkdir()
    (tmp_path / "dup" / "CAM 1 copy.mp4").write_bytes(b"b")

    cameras = [_cam("CAM 1", "id-1")]
    targets, unmatched = build_video_targets(cameras, video_root=tmp_path)
    assert len(targets) == 1
    assert targets[0].camera.id == "id-1"
    assert [p.name for p in unmatched] == ["CAM 1 copy.mp4"]
