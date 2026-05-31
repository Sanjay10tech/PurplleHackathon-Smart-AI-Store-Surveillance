# PROMPT:
# Unit tests for store layout → heatmap zone remapping.
#
# CHANGES MADE:
# - Camera zone_id rollup to layout zones and FOH merge across cameras.

import pytest

from app.domain.heatmap.calculator import RawZoneVisit
from app.domain.heatmap.layout_mapping import load_store_layout


@pytest.fixture
def brigade_layout():
    return load_store_layout()


class TestStoreLayoutMapping:
    def test_maps_camera_zone_to_layout_label(self, brigade_layout) -> None:
        visit = RawZoneVisit("id:zone-cam5-checkout", "checkout_active", is_enter=True)
        remapped = brigade_layout.remap_visit(visit, camera_zone_id="zone-cam5-checkout")
        assert remapped.zone_key == "layout:cash_counter"
        assert remapped.zone_label == "Cash Counter"

    def test_merges_aisle_zones_into_foh(self, brigade_layout) -> None:
        visits = [
            RawZoneVisit("id:zone-cam1-aisle", "aisle_circulation", is_enter=True),
            RawZoneVisit("id:zone-cam2-aisle", "aisle_circulation", is_enter=True),
        ]
        remapped = brigade_layout.remap_visits(
            visits, camera_zone_ids=["zone-cam1-aisle", "zone-cam2-aisle"]
        )
        keys = {v.zone_key for v in remapped}
        assert keys == {"layout:foh_circulation"}

        result_keys = {
            z.zone_key
            for z in __import__(
                "app.domain.heatmap.calculator", fromlist=["HeatmapCalculator"]
            ).HeatmapCalculator.compute(remapped).zones
        }
        assert result_keys == {"layout:foh_circulation"}

    def test_zone_type_fallback_when_no_zone_id(self, brigade_layout) -> None:
        visit = RawZoneVisit("type:billing_queue", "billing_queue", is_enter=True)
        remapped = brigade_layout.remap_visit(visit, camera_zone_id=None)
        assert remapped.zone_key == "layout:billing_queue"

    def test_layout_zone_catalog_covers_checkout(self, brigade_layout) -> None:
        mapped_targets = set(brigade_layout.camera_zone_mapping.values())
        assert "cash_counter" in mapped_targets
        assert "billing_queue" in mapped_targets
        assert "entrance" in mapped_targets

    def test_brand_bays_documented(self, brigade_layout) -> None:
        north = brigade_layout.brand_bays.get("north_wall", [])
        south = brigade_layout.brand_bays.get("south_wall", [])
        assert len(north) >= 7
        assert len(south) >= 8
        assert any(b["label"] == "Maybelline" for b in south)
