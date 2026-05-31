"""Load pipeline configuration from YAML with PIPELINE_* env overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PIPELINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_DIR.parent
DEFAULT_CONFIG_PATH = PIPELINE_DIR / "config.yaml"
DEFAULT_ZONES_PATH = PIPELINE_DIR / "zones.yaml"


def resolve_video_path(video: str) -> Path:
    """Resolve camera video paths relative to repo root or PIPELINE_VIDEO_ROOT."""
    raw = Path(video)
    if raw.is_absolute():
        return raw
    root = Path(os.environ.get("PIPELINE_VIDEO_ROOT", REPO_ROOT))
    return (root / raw).resolve()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _env_overrides() -> dict[str, Any]:
    """Map select PIPELINE_* env vars into nested config keys."""
    mapping: dict[str, tuple[str, ...]] = {
        "PIPELINE_STORE_ID": ("store_id",),
        "PIPELINE_TENANT_ID": ("tenant_id",),
        "PIPELINE_DETECTOR_MODE": ("detector", "mode"),
        "PIPELINE_DETECTOR_MODEL": ("detector", "model"),
        "PIPELINE_DETECTOR_CONFIDENCE": ("detector", "confidence"),
        "PIPELINE_SAMPLE_FPS": ("processing", "sample_fps"),
        "PIPELINE_API_URL": ("emit", "api_url"),
        "PIPELINE_POST_TO_API": ("emit", "post_to_api"),
        "PIPELINE_PERSIST_SESSIONS": ("emit", "persist_sessions"),
        "PIPELINE_OUTPUT_JSONL": ("emit", "output_jsonl"),
        "PIPELINE_REID_ENABLED": ("reid", "enabled"),
        "PIPELINE_REID_MATCH_THRESHOLD": ("reid", "match_score_threshold"),
        "PIPELINE_REENTRY_COOLDOWN_MINUTES": ("session", "reentry_cooldown_minutes"),
    }
    overrides: dict[str, Any] = {}
    for env_key, path in mapping.items():
        raw = os.environ.get(env_key)
        if raw is None:
            continue
        node: dict[str, Any] = overrides
        for part in path[:-1]:
            node = node.setdefault(part, {})
        leaf = path[-1]
        if leaf in ("confidence", "sample_fps", "match_score_threshold", "reentry_cooldown_minutes"):
            node[leaf] = float(raw) if "." in raw else int(raw)
        elif leaf in ("post_to_api", "enabled", "persist_sessions", "validate_before_post"):
            node[leaf] = raw.lower() in ("1", "true", "yes", "on")
        else:
            node[leaf] = raw
    return overrides


@dataclass
class CameraConfig:
    id: str
    name: str
    role: str
    video: str


@dataclass
class PipelineConfig:
    store_id: str
    tenant_id: str
    schema_version: str
    detector: dict[str, Any]
    tracker: dict[str, Any]
    processing: dict[str, Any]
    reid: dict[str, Any]
    staff: dict[str, Any]
    session: dict[str, Any]
    emit: dict[str, Any]
    overlap_dedup: dict[str, Any]
    zone_analysis: dict[str, Any]
    cameras: list[CameraConfig]
    camera_graph: list[dict[str, Any]]
    zones_by_camera: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        config_path: Path | None = None,
        zones_path: Path | None = None,
    ) -> PipelineConfig:
        config_path = config_path or DEFAULT_CONFIG_PATH
        zones_path = zones_path or DEFAULT_ZONES_PATH

        with config_path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        raw = _deep_merge(raw, _env_overrides())

        zones_raw: dict[str, list[dict[str, Any]]] = {}
        if zones_path.exists():
            with zones_path.open(encoding="utf-8") as fh:
                zones_doc = yaml.safe_load(fh) or {}
            zones_raw = zones_doc.get("zones", {})

        cameras = [
            CameraConfig(
                id=str(c["id"]),
                name=str(c["name"]),
                role=str(c["role"]),
                video=str(resolve_video_path(str(c["video"]))),
            )
            for c in raw.get("cameras", [])
        ]

        return cls(
            store_id=str(raw["store_id"]),
            tenant_id=str(raw["tenant_id"]),
            schema_version=str(raw.get("schema_version", "1.0.0")),
            detector=dict(raw.get("detector", {})),
            tracker=dict(raw.get("tracker", {})),
            processing=dict(raw.get("processing", {})),
            reid=dict(raw.get("reid", {})),
            staff=dict(raw.get("staff", {})),
            session=dict(raw.get("session", {})),
            emit=dict(raw.get("emit", {})),
            overlap_dedup=dict(raw.get("overlap_dedup", {})),
            zone_analysis=dict(raw.get("zone_analysis", {})),
            cameras=cameras,
            camera_graph=list(raw.get("camera_graph", [])),
            zones_by_camera=zones_raw,
        )
