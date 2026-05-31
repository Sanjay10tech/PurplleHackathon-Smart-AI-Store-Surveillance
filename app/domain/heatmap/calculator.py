from dataclasses import dataclass


@dataclass(frozen=True)
class RawZoneVisit:
    """Zone observation — enter events count visits; exits contribute dwell samples."""

    zone_key: str
    zone_label: str
    is_enter: bool
    dwell_seconds: float | None = None


@dataclass
class HeatmapZoneMetrics:
    zone_key: str
    zone_label: str
    visit_count: int
    avg_dwell_seconds: float | None
    dwell_sample_count: int
    normalized_visit_score: float
    normalized_dwell_score: float
    data_confidence: str


@dataclass
class HeatmapComputationResult:
    zones: list[HeatmapZoneMetrics]
    total_visits: int
    zones_with_dwell: int


class HeatmapCalculator:
    """
    Pure zone heatmap computation — no I/O.

    Normalizes visit frequency and dwell across zones via min-max scaling (0–1).
    """

    @classmethod
    def compute(
        cls,
        visits: list[RawZoneVisit],
        *,
        min_samples_high: int = 5,
        min_samples_medium: int = 3,
    ) -> HeatmapComputationResult:
        aggregates: dict[str, dict] = {}

        for visit in visits:
            bucket = aggregates.setdefault(
                visit.zone_key,
                {
                    "zone_label": visit.zone_label,
                    "visit_count": 0,
                    "dwell_total": 0.0,
                    "dwell_samples": 0,
                },
            )
            if visit.is_enter:
                bucket["visit_count"] += 1
            if visit.dwell_seconds is not None and visit.dwell_seconds >= 0:
                bucket["dwell_total"] += visit.dwell_seconds
                bucket["dwell_samples"] += 1

        if not aggregates:
            return HeatmapComputationResult(zones=[], total_visits=0, zones_with_dwell=0)

        visit_counts = [b["visit_count"] for b in aggregates.values()]
        avg_dwells = [
            b["dwell_total"] / b["dwell_samples"]
            for b in aggregates.values()
            if b["dwell_samples"] > 0
        ]

        visit_min, visit_max = min(visit_counts), max(visit_counts)
        dwell_min = min(avg_dwells) if avg_dwells else 0.0
        dwell_max = max(avg_dwells) if avg_dwells else 0.0

        zones: list[HeatmapZoneMetrics] = []
        total_visits = 0
        zones_with_dwell = 0

        for zone_key, bucket in sorted(aggregates.items(), key=lambda item: item[0]):
            visit_count = bucket["visit_count"]
            dwell_samples = bucket["dwell_samples"]
            avg_dwell = (
                bucket["dwell_total"] / dwell_samples if dwell_samples > 0 else None
            )

            normalized_visit = cls._normalize(visit_count, visit_min, visit_max)
            normalized_dwell = (
                cls._normalize(avg_dwell, dwell_min, dwell_max)
                if avg_dwell is not None
                else 0.0
            )
            confidence = cls._confidence(
                visit_count=visit_count,
                dwell_samples=dwell_samples,
                min_samples_high=min_samples_high,
                min_samples_medium=min_samples_medium,
            )

            total_visits += visit_count
            if dwell_samples > 0:
                zones_with_dwell += 1

            zones.append(
                HeatmapZoneMetrics(
                    zone_key=zone_key,
                    zone_label=bucket["zone_label"],
                    visit_count=visit_count,
                    avg_dwell_seconds=round(avg_dwell, 2) if avg_dwell is not None else None,
                    dwell_sample_count=dwell_samples,
                    normalized_visit_score=round(normalized_visit, 4),
                    normalized_dwell_score=round(normalized_dwell, 4),
                    data_confidence=confidence,
                )
            )

        zones.sort(key=lambda z: z.visit_count, reverse=True)
        return HeatmapComputationResult(
            zones=zones,
            total_visits=total_visits,
            zones_with_dwell=zones_with_dwell,
        )

    @staticmethod
    def _normalize(value: float, minimum: float, maximum: float) -> float:
        if maximum <= minimum:
            return 1.0 if value > 0 else 0.0
        return (value - minimum) / (maximum - minimum)

    @staticmethod
    def _confidence(
        *,
        visit_count: int,
        dwell_samples: int,
        min_samples_high: int,
        min_samples_medium: int,
    ) -> str:
        if visit_count < min_samples_medium:
            return "LOW"
        dwell_coverage = dwell_samples / visit_count if visit_count else 0.0
        if visit_count >= min_samples_high and dwell_coverage >= 0.5:
            return "HIGH"
        if dwell_samples == 0:
            return "LOW"
        return "MEDIUM"
