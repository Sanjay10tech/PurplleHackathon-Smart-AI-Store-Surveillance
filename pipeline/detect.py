"""YOLOv11 person detection adapter.

Configurable via ``detector`` section in ``pipeline/config.yaml`` or env vars
``PIPELINE_DETECTOR_*`` (see ``pipeline/config.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass(frozen=True)
class RawDetection:
    """Single person detection in normalized coordinates."""

    bbox_xywh: tuple[float, float, float, float]  # x, y, w, h in [0, 1]
    confidence: float
    class_id: int = 0


class PersonDetector(Protocol):
    def detect(self, frame_bgr: np.ndarray) -> list[RawDetection]: ...


class TrajectoryMockPersonDetector:
    """Synthetic person that walks a foot-point path — for integration / e2e tests."""

    def __init__(
        self,
        foot_points: list[tuple[float, float]],
        *,
        confidence: float = 0.92,
        bbox_size: tuple[float, float] = (0.08, 0.22),
    ) -> None:
        self._foot_points = foot_points or [(0.5, 0.55)]
        self._confidence = confidence
        self._bw, self._bh = bbox_size
        self._index = 0

    def detect(self, frame_bgr: np.ndarray) -> list[RawDetection]:
        h, w = frame_bgr.shape[:2]
        if h == 0 or w == 0:
            return []
        idx = min(self._index, len(self._foot_points) - 1)
        fx, fy = self._foot_points[idx]
        if self._index < len(self._foot_points) - 1:
            self._index += 1
        x = max(0.0, fx - self._bw / 2)
        y = max(0.0, fy - self._bh)
        return [
            RawDetection(
                bbox_xywh=(x, y, self._bw, self._bh),
                confidence=self._confidence,
                class_id=0,
            )
        ]


class MockPersonDetector:
    """Deterministic detector for CI / dry runs without GPU weights."""

    def __init__(self, *, confidence: float = 0.9) -> None:
        self._confidence = confidence

    def detect(self, frame_bgr: np.ndarray) -> list[RawDetection]:
        h, w = frame_bgr.shape[:2]
        if h == 0 or w == 0:
            return []
        # Place a synthetic person near frame center.
        cx, cy = 0.5, 0.55
        bw, bh = 0.08, 0.22
        return [
            RawDetection(
                bbox_xywh=(cx - bw / 2, cy - bh / 2, bw, bh),
                confidence=self._confidence,
                class_id=0,
            )
        ]


class YoloV11PersonDetector:
    """Ultralytics YOLOv11 person-only detector."""

    def __init__(self, detector_cfg: dict[str, Any]) -> None:
        from ultralytics import YOLO

        model_name = str(detector_cfg.get("model", "yolo11n.pt"))
        self._model = YOLO(model_name)
        self._confidence = float(detector_cfg.get("confidence", 0.45))
        self._iou = float(detector_cfg.get("iou", 0.50))
        self._person_class = int(detector_cfg.get("person_class_id", 0))
        self._imgsz = int(detector_cfg.get("imgsz", 640))
        self._max_det = int(detector_cfg.get("max_det", 10))
        self._min_bbox_h = float(detector_cfg.get("min_bbox_height", 0.08))
        self._min_bbox_area = float(detector_cfg.get("min_bbox_area", 0.006))
        self._max_bbox_area = float(detector_cfg.get("max_bbox_area", 0.32))
        self._min_aspect = float(detector_cfg.get("min_aspect_ratio", 1.2))
        self._max_aspect = float(detector_cfg.get("max_aspect_ratio", 5.5))
        device = detector_cfg.get("device") or None
        self._device = device if device else None

    def _passes_filters(self, nw: float, nh: float, conf: float) -> bool:
        area = nw * nh
        if nh < self._min_bbox_h or area < self._min_bbox_area:
            return False
        if area > self._max_bbox_area:
            return False
        aspect = nh / max(nw, 1e-6)
        if aspect < self._min_aspect or aspect > self._max_aspect:
            return False
        if conf < self._confidence:
            return False
        return True

    def detect(self, frame_bgr: np.ndarray) -> list[RawDetection]:
        h, w = frame_bgr.shape[:2]
        if h == 0 or w == 0:
            return []

        results = self._model.predict(
            source=frame_bgr,
            conf=self._confidence,
            iou=self._iou,
            classes=[self._person_class],
            imgsz=self._imgsz,
            max_det=self._max_det,
            device=self._device,
            verbose=False,
        )
        if not results:
            return []

        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            return []

        detections: list[RawDetection] = []
        boxes = result.boxes.xywh.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy().astype(int)

        for (xc, yc, bw, bh), conf, cls_id in zip(boxes, confs, classes, strict=True):
            nw = float(bw / w)
            nh = float(bh / h)
            if not self._passes_filters(nw, nh, float(conf)):
                continue
            x = float((xc - bw / 2) / w)
            y = float((yc - bh / 2) / h)
            detections.append(
                RawDetection(
                    bbox_xywh=(
                        max(0.0, min(1.0, x)),
                        max(0.0, min(1.0, y)),
                        max(0.0, min(1.0, nw)),
                        max(0.0, min(1.0, nh)),
                    ),
                    confidence=float(conf),
                    class_id=int(cls_id),
                )
            )
        return detections


def build_detector(detector_cfg: dict[str, Any]) -> PersonDetector:
    mode = str(detector_cfg.get("mode", "yolo")).lower()
    if mode == "mock":
        conf = float(detector_cfg.get("confidence", 0.9))
        conf = max(conf, 0.55)
        return MockPersonDetector(confidence=conf)
    if mode == "trajectory":
        points_raw = detector_cfg.get("foot_points", [[0.5, 0.55]])
        foot_points = [(float(p[0]), float(p[1])) for p in points_raw]
        return TrajectoryMockPersonDetector(foot_points)
    return YoloV11PersonDetector(detector_cfg)


def build_detectors_for_cameras(
    detector_cfg: dict[str, Any],
    cameras: list[Any],
) -> PersonDetector | dict[str, PersonDetector]:
    """
    When mock mode includes per-camera trajectories, return a detector map so
    real video frames produce zone crossings (entry, aisle, billing queue).

    In YOLO mode, optional ``per_camera`` overrides tune confidence/IoU per view.
    """
    mode = str(detector_cfg.get("mode", "yolo")).lower()
    if mode == "mock":
        trajectories: dict[str, list] = detector_cfg.get("mock_trajectories") or {}
        if not trajectories:
            return build_detector(detector_cfg)

        conf = max(float(detector_cfg.get("confidence", 0.9)), 0.55)
        detectors: dict[str, PersonDetector] = {}
        for cam in cameras:
            cam_id = cam.id if hasattr(cam, "id") else str(cam["id"])
            points_raw = trajectories.get(cam_id)
            if points_raw:
                foot_points = [(float(p[0]), float(p[1])) for p in points_raw]
                detectors[cam_id] = TrajectoryMockPersonDetector(foot_points, confidence=conf)
            else:
                detectors[cam_id] = MockPersonDetector(confidence=conf)
        return detectors

    per_camera: dict[str, dict[str, Any]] = detector_cfg.get("per_camera") or {}
    if not per_camera:
        return build_detector(detector_cfg)

    detectors: dict[str, PersonDetector] = {}
    for cam in cameras:
        cam_id = cam.id if hasattr(cam, "id") else str(cam["id"])
        merged = dict(detector_cfg)
        merged.update(per_camera.get(cam_id, {}))
        detectors[cam_id] = YoloV11PersonDetector(merged)
    return detectors
