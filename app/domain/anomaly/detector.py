from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from app.domain.anomaly.types import AnomalySeverity, AnomalyType

ANOMALY_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


@dataclass(frozen=True)
class ZoneVisitSummary:
    zone_key: str
    zone_label: str
    visit_count: int


@dataclass(frozen=True)
class ConversionSummary:
    entry_count: int
    purchase_count: int

    @property
    def rate(self) -> float | None:
        if self.entry_count == 0:
            return None
        return self.purchase_count / self.entry_count


@dataclass
class AnomalyThresholds:
    queue_spike_ratio_warn: float = 1.5
    queue_spike_ratio_critical: float = 2.5
    queue_spike_min_baseline_visits: int = 5
    conversion_drop_pp_warn: float = 0.15
    conversion_drop_pp_critical: float = 0.30
    conversion_min_entry: int = 10
    dead_zone_ratio: float = 0.05
    dead_zone_min_store_visits: int = 20
    dead_zone_min_zones: int = 2
    stale_feed_warn_minutes: int = 15
    stale_feed_critical_minutes: int = 60


@dataclass
class DetectedAnomaly:
    id: UUID
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    detected_at: datetime
    message: str
    suggested_action: str
    context: dict[str, Any] = field(default_factory=dict)


class AnomalyDetector:
    """Rule-based anomaly detection — no I/O."""

    @classmethod
    def detect(
        cls,
        *,
        store_id: UUID,
        period_end: datetime,
        current_queue: list[ZoneVisitSummary],
        baseline_queue: list[ZoneVisitSummary],
        current_conversion: ConversionSummary,
        baseline_conversion: ConversionSummary,
        zone_visits: list[ZoneVisitSummary],
        last_feed_at: datetime | None,
        queue_zone_keys: set[str],
        thresholds: AnomalyThresholds | None = None,
    ) -> list[DetectedAnomaly]:
        cfg = thresholds or AnomalyThresholds()
        detected: list[DetectedAnomaly] = []

        detected.extend(
            cls._detect_queue_spikes(
                store_id,
                period_end,
                current_queue,
                baseline_queue,
                queue_zone_keys,
                cfg,
            )
        )
        detected.extend(
            cls._detect_conversion_drop(
                store_id,
                period_end,
                current_conversion,
                baseline_conversion,
                cfg,
            )
        )
        detected.extend(
            cls._detect_dead_zones(
                store_id,
                period_end,
                zone_visits,
                cfg,
            )
        )
        stale = cls._detect_stale_feed(store_id, period_end, last_feed_at, cfg)
        if stale is not None:
            detected.append(stale)

        severity_order = {
            AnomalySeverity.CRITICAL: 0,
            AnomalySeverity.WARN: 1,
            AnomalySeverity.INFO: 2,
        }
        detected.sort(key=lambda item: (severity_order[item.severity], item.detected_at), reverse=False)
        return detected

    @classmethod
    def _detect_queue_spikes(
        cls,
        store_id: UUID,
        period_end: datetime,
        current: list[ZoneVisitSummary],
        baseline: list[ZoneVisitSummary],
        queue_zone_keys: set[str],
        cfg: AnomalyThresholds,
    ) -> list[DetectedAnomaly]:
        baseline_map = {z.zone_key: z.visit_count for z in baseline}
        results: list[DetectedAnomaly] = []

        for zone in current:
            if queue_zone_keys and zone.zone_key not in queue_zone_keys:
                zone_type = zone.zone_key.split(":", 1)[-1] if ":" in zone.zone_key else zone.zone_key
                if zone_type not in queue_zone_keys:
                    continue

            baseline_count = baseline_map.get(zone.zone_key, 0)
            if baseline_count < cfg.queue_spike_min_baseline_visits:
                continue
            if zone.visit_count <= baseline_count:
                continue

            ratio = zone.visit_count / baseline_count
            if ratio >= cfg.queue_spike_ratio_critical:
                severity = AnomalySeverity.CRITICAL
                action = (
                    "Open additional checkout lanes immediately and notify floor staff "
                    "to redirect traffic away from congested queue zones."
                )
            elif ratio >= cfg.queue_spike_ratio_warn:
                severity = AnomalySeverity.WARN
                action = (
                    "Monitor queue length and prepare to reassign staff to billing "
                    "or activate overflow queue signage."
                )
            else:
                continue

            results.append(
                DetectedAnomaly(
                    id=cls._anomaly_id(store_id, AnomalyType.QUEUE_SPIKE, zone.zone_key, period_end),
                    anomaly_type=AnomalyType.QUEUE_SPIKE,
                    severity=severity,
                    detected_at=period_end,
                    message=(
                        f"Queue spike in {zone.zone_label}: {zone.visit_count} visits "
                        f"vs baseline {baseline_count} ({ratio:.1f}x)."
                    ),
                    suggested_action=action,
                    context={
                        "zone_key": zone.zone_key,
                        "current_visits": zone.visit_count,
                        "baseline_visits": baseline_count,
                        "spike_ratio": round(ratio, 2),
                    },
                )
            )
        return results

    @classmethod
    def _detect_conversion_drop(
        cls,
        store_id: UUID,
        period_end: datetime,
        current: ConversionSummary,
        baseline: ConversionSummary,
        cfg: AnomalyThresholds,
    ) -> list[DetectedAnomaly]:
        if current.entry_count < cfg.conversion_min_entry:
            return []

        current_rate = current.rate
        baseline_rate = baseline.rate
        if current_rate is None or baseline_rate is None:
            return []

        drop_pp = baseline_rate - current_rate
        if drop_pp <= 0:
            return []

        if drop_pp >= cfg.conversion_drop_pp_critical:
            severity = AnomalySeverity.CRITICAL
            action = (
                "Investigate checkout failures, staffing gaps, and out-of-stock items; "
                "review live camera feeds for billing-area bottlenecks."
            )
        elif drop_pp >= cfg.conversion_drop_pp_warn:
            severity = AnomalySeverity.WARN
            action = (
                "Compare current funnel stage drop-offs with baseline and verify "
                "POS integration and queue wait times."
            )
        else:
            return []

        return [
            DetectedAnomaly(
                id=cls._anomaly_id(store_id, AnomalyType.CONVERSION_DROP, "global", period_end),
                anomaly_type=AnomalyType.CONVERSION_DROP,
                severity=severity,
                detected_at=period_end,
                message=(
                    f"Conversion dropped {drop_pp:.0%} (baseline {baseline_rate:.0%} → "
                    f"current {current_rate:.0%}, {current.purchase_count}/{current.entry_count} purchases)."
                ),
                suggested_action=action,
                context={
                    "current_rate": round(current_rate, 4),
                    "baseline_rate": round(baseline_rate, 4),
                    "drop_percentage_points": round(drop_pp, 4),
                    "current_entry_count": current.entry_count,
                    "current_purchase_count": current.purchase_count,
                },
            )
        ]

    @classmethod
    def _detect_dead_zones(
        cls,
        store_id: UUID,
        period_end: datetime,
        zone_visits: list[ZoneVisitSummary],
        cfg: AnomalyThresholds,
    ) -> list[DetectedAnomaly]:
        if len(zone_visits) < cfg.dead_zone_min_zones:
            return []

        total_visits = sum(z.visit_count for z in zone_visits)
        if total_visits < cfg.dead_zone_min_store_visits:
            return []

        peak = max(z.visit_count for z in zone_visits)
        if peak == 0:
            return []

        threshold = peak * cfg.dead_zone_ratio
        results: list[DetectedAnomaly] = []

        for zone in zone_visits:
            if zone.visit_count > threshold:
                continue
            share = zone.visit_count / total_visits if total_visits else 0.0
            severity = AnomalySeverity.WARN if share < cfg.dead_zone_ratio / 2 else AnomalySeverity.INFO
            results.append(
                DetectedAnomaly(
                    id=cls._anomaly_id(store_id, AnomalyType.DEAD_ZONE, zone.zone_key, period_end),
                    anomaly_type=AnomalyType.DEAD_ZONE,
                    severity=severity,
                    detected_at=period_end,
                    message=(
                        f"Dead zone detected: {zone.zone_label} had only {zone.visit_count} visits "
                        f"({share:.1%} of store traffic, peak zone {peak})."
                    ),
                    suggested_action=(
                        "Review merchandising, signage, and camera coverage for this zone; "
                        "consider A/B layout changes or promotional placement."
                    ),
                    context={
                        "zone_key": zone.zone_key,
                        "visit_count": zone.visit_count,
                        "traffic_share": round(share, 4),
                        "peak_zone_visits": peak,
                    },
                )
            )
        return results

    @classmethod
    def _detect_stale_feed(
        cls,
        store_id: UUID,
        period_end: datetime,
        last_feed_at: datetime | None,
        cfg: AnomalyThresholds,
    ) -> DetectedAnomaly | None:
        if last_feed_at is None:
            return DetectedAnomaly(
                id=cls._anomaly_id(store_id, AnomalyType.STALE_FEED, "none", period_end),
                anomaly_type=AnomalyType.STALE_FEED,
                severity=AnomalySeverity.CRITICAL,
                detected_at=period_end,
                message="No vision feed events recorded for this store.",
                suggested_action=(
                    "Verify camera connectivity, ingestion pipeline health, and worker "
                    "process status; check RTSP credentials and frame source configuration."
                ),
                context={"last_feed_at": None, "minutes_since_feed": None},
            )

        last_feed_at = cls._as_utc(last_feed_at)
        minutes_stale = (cls._as_utc(period_end) - last_feed_at).total_seconds() / 60.0
        if minutes_stale < cfg.stale_feed_warn_minutes:
            return None

        if minutes_stale >= cfg.stale_feed_critical_minutes:
            severity = AnomalySeverity.CRITICAL
            action = (
                "Restart ingestion workers and validate camera streams immediately; "
                "analytics are unreliable until the feed recovers."
            )
        else:
            severity = AnomalySeverity.WARN
            action = (
                "Check pipeline lag and camera heartbeat; confirm detection workers "
                "are consuming frames without backlog."
            )

        return DetectedAnomaly(
            id=cls._anomaly_id(store_id, AnomalyType.STALE_FEED, "feed", period_end),
            anomaly_type=AnomalyType.STALE_FEED,
            severity=severity,
            detected_at=period_end,
            message=f"Vision feed stale: last event {minutes_stale:.0f} minutes ago.",
            suggested_action=action,
            context={
                "last_feed_at": last_feed_at.isoformat(),
                "minutes_since_feed": round(minutes_stale, 1),
            },
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _anomaly_id(
        store_id: UUID,
        anomaly_type: AnomalyType,
        scope: str,
        period_end: datetime,
    ) -> UUID:
        bucket = period_end.replace(minute=0, second=0, microsecond=0).isoformat()
        return uuid5(ANOMALY_NAMESPACE, f"{store_id}:{anomaly_type}:{scope}:{bucket}")
