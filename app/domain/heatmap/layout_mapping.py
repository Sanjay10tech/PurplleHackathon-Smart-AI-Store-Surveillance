"""Store floor-plan zone registry and camera→layout remapping for heatmaps."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.domain.heatmap.calculator import RawZoneVisit

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LAYOUT_PATH = Path(__file__).resolve().parent / "brigade_road_layout.yaml"
FALLBACK_LAYOUT_PATH = REPO_ROOT / "data" / "store_layout" / "brigade_road_layout.yaml"


@dataclass(frozen=True)
class LayoutZone:
    id: str
    label: str
    section: str
    plan_position: str = ""
    description: str = ""


@dataclass(frozen=True)
class StoreLayout:
    store_id: str
    store_code: str
    store_name: str
    layout_version: str
    source_file: str
    zones_by_id: dict[str, LayoutZone]
    sections: dict[str, dict[str, str]]
    camera_zone_mapping: dict[str, str]
    zone_type_mapping: dict[str, str | None]
    brand_bays: dict[str, list[dict[str, Any]]]

    def resolve_layout_zone(
        self,
        *,
        zone_id: str | None = None,
        zone_type: str | None = None,
    ) -> LayoutZone | None:
        layout_id: str | None = None
        if zone_id:
            layout_id = self.camera_zone_mapping.get(zone_id)
        if layout_id is None and zone_type:
            layout_id = self.zone_type_mapping.get(str(zone_type).lower())
        if layout_id is None:
            return None
        return self.zones_by_id.get(layout_id)

    def remap_visit(self, visit: RawZoneVisit, *, camera_zone_id: str | None) -> RawZoneVisit:
        zone_type = None
        if visit.zone_key.startswith("type:"):
            zone_type = visit.zone_key.removeprefix("type:")
        elif visit.zone_key.startswith("id:"):
            camera_zone_id = camera_zone_id or visit.zone_key.removeprefix("id:")

        layout = self.resolve_layout_zone(zone_id=camera_zone_id, zone_type=zone_type)
        if layout is None:
            return visit

        return RawZoneVisit(
            zone_key=f"layout:{layout.id}",
            zone_label=layout.label,
            is_enter=visit.is_enter,
            dwell_seconds=visit.dwell_seconds,
        )

    def remap_visits(
        self,
        visits: list[RawZoneVisit],
        *,
        camera_zone_ids: list[str | None] | None = None,
    ) -> list[RawZoneVisit]:
        if camera_zone_ids is None:
            camera_zone_ids = [None] * len(visits)
        return [
            self.remap_visit(visit, camera_zone_id=camera_id)
            for visit, camera_id in zip(visits, camera_zone_ids, strict=True)
        ]

    @property
    def layout_zone_ids(self) -> set[str]:
        return set(self.zones_by_id)


def load_store_layout(path: Path | str | None = None) -> StoreLayout:
    if path:
        layout_path = Path(path)
    elif DEFAULT_LAYOUT_PATH.exists():
        layout_path = DEFAULT_LAYOUT_PATH
    else:
        layout_path = FALLBACK_LAYOUT_PATH
    with layout_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    zones_by_id: dict[str, LayoutZone] = {}
    for item in raw.get("layout_zones", []):
        zones_by_id[item["id"]] = LayoutZone(
            id=item["id"],
            label=item["label"],
            section=item.get("section", "foh"),
            plan_position=item.get("plan_position", ""),
            description=item.get("description", ""),
        )

    zone_type_mapping = {
        str(k).lower(): v for k, v in raw.get("zone_type_mapping", {}).items()
    }

    return StoreLayout(
        store_id=str(raw.get("store_id", "")),
        store_code=str(raw.get("store_code", "")),
        store_name=str(raw.get("store_name", "")),
        layout_version=str(raw.get("layout_version", "")),
        source_file=str(raw.get("source_file", "")),
        zones_by_id=zones_by_id,
        sections=raw.get("sections", {}),
        camera_zone_mapping=dict(raw.get("camera_zone_mapping", {})),
        zone_type_mapping=zone_type_mapping,
        brand_bays=dict(raw.get("brand_bays", {})),
    )


@lru_cache(maxsize=8)
def get_layout_for_store(store_id: str, layout_path: str | None = None) -> StoreLayout | None:
    path = Path(layout_path) if layout_path else DEFAULT_LAYOUT_PATH
    if not path.exists():
        return None
    layout = load_store_layout(path)
    if layout.store_id and layout.store_id != store_id:
        return None
    return layout
