# PROMPT:
# Generate complete pytest suite — pure HeatmapCalculator unit tests.
#
# CHANGES MADE:
# - Visit/dwell aggregation, min-max normalization, and data-confidence tiers.

import pytest

from app.domain.heatmap.calculator import HeatmapCalculator, RawZoneVisit


class TestHeatmapCalculator:
    def test_aggregates_visits_and_dwell(self) -> None:
        visits = [
            RawZoneVisit("type:browse", "browse", is_enter=True),
            RawZoneVisit("type:browse", "browse", is_enter=True),
            RawZoneVisit("type:browse", "browse", is_enter=False, dwell_seconds=30.0),
            RawZoneVisit("type:browse", "browse", is_enter=False, dwell_seconds=50.0),
            RawZoneVisit("type:checkout", "checkout", is_enter=True),
            RawZoneVisit("type:checkout", "checkout", is_enter=False, dwell_seconds=10.0),
        ]
        result = HeatmapCalculator.compute(visits)

        zones = {z.zone_key: z for z in result.zones}
        assert zones["type:browse"].visit_count == 2
        assert zones["type:browse"].avg_dwell_seconds == 40.0
        assert zones["type:browse"].dwell_sample_count == 2
        assert zones["type:checkout"].visit_count == 1
        assert zones["type:checkout"].normalized_visit_score == 0.0
        assert zones["type:browse"].normalized_visit_score == 1.0

    def test_normalization_single_zone(self) -> None:
        visits = [
            RawZoneVisit("type:browse", "browse", is_enter=True),
            RawZoneVisit("type:browse", "browse", is_enter=False, dwell_seconds=20.0),
        ]
        result = HeatmapCalculator.compute(visits)
        zone = result.zones[0]
        assert zone.normalized_visit_score == 1.0
        assert zone.normalized_dwell_score == 1.0

    def test_data_confidence_levels(self) -> None:
        low = HeatmapCalculator.compute(
            [RawZoneVisit("type:a", "a", is_enter=True)],
            min_samples_high=5,
            min_samples_medium=3,
        )
        assert low.zones[0].data_confidence == "LOW"

        medium = HeatmapCalculator.compute(
            [
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=False, dwell_seconds=10.0),
            ],
            min_samples_high=5,
            min_samples_medium=3,
        )
        assert medium.zones[0].data_confidence == "MEDIUM"

        high = HeatmapCalculator.compute(
            [
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=True),
                RawZoneVisit("type:a", "a", is_enter=False, dwell_seconds=10.0),
                RawZoneVisit("type:a", "a", is_enter=False, dwell_seconds=20.0),
                RawZoneVisit("type:a", "a", is_enter=False, dwell_seconds=30.0),
            ],
            min_samples_high=5,
            min_samples_medium=3,
        )
        assert high.zones[0].data_confidence == "HIGH"

    def test_empty_period(self) -> None:
        result = HeatmapCalculator.compute([])
        assert result.zones == []
        assert result.total_visits == 0
