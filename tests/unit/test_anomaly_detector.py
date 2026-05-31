# PROMPT:
# Generate complete pytest suite — pure AnomalyDetector rule unit tests.
#
# CHANGES MADE:
# - Unit coverage for QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, STALE_FEED, and healthy baseline.

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.anomaly.detector import (
    AnomalyDetector,
    AnomalyThresholds,
    ConversionSummary,
    ZoneVisitSummary,
)
from app.domain.anomaly.types import AnomalySeverity, AnomalyType


STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")
PERIOD_END = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


class TestAnomalyDetector:
    def test_queue_spike_critical(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[ZoneVisitSummary("type:checkout", "checkout", 25)],
            baseline_queue=[ZoneVisitSummary("type:checkout", "checkout", 8)],
            current_conversion=ConversionSummary(0, 0),
            baseline_conversion=ConversionSummary(0, 0),
            zone_visits=[],
            last_feed_at=PERIOD_END - timedelta(minutes=1),
            queue_zone_keys={"type:checkout"},
            thresholds=AnomalyThresholds(queue_spike_min_baseline_visits=5),
        )
        spike = next(r for r in results if r.anomaly_type == AnomalyType.QUEUE_SPIKE)
        assert spike.severity == AnomalySeverity.CRITICAL
        assert spike.suggested_action

    def test_conversion_drop_warn(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[],
            baseline_queue=[],
            current_conversion=ConversionSummary(entry_count=20, purchase_count=5),
            baseline_conversion=ConversionSummary(entry_count=20, purchase_count=10),
            zone_visits=[],
            last_feed_at=PERIOD_END - timedelta(minutes=1),
            queue_zone_keys=set(),
            thresholds=AnomalyThresholds(conversion_min_entry=10),
        )
        drop = next(r for r in results if r.anomaly_type == AnomalyType.CONVERSION_DROP)
        assert drop.severity == AnomalySeverity.WARN
        assert "25%" in drop.message or "25" in drop.message

    def test_dead_zone(self) -> None:
        zones = [
            ZoneVisitSummary("type:browse", "browse", 100),
            ZoneVisitSummary("type:back", "back", 2),
        ]
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[],
            baseline_queue=[],
            current_conversion=ConversionSummary(0, 0),
            baseline_conversion=ConversionSummary(0, 0),
            zone_visits=zones,
            last_feed_at=PERIOD_END - timedelta(minutes=1),
            queue_zone_keys=set(),
            thresholds=AnomalyThresholds(dead_zone_min_store_visits=20),
        )
        dead = next(r for r in results if r.anomaly_type == AnomalyType.DEAD_ZONE)
        assert dead.context["zone_key"] == "type:back"

    def test_stale_feed_critical_when_no_events(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[],
            baseline_queue=[],
            current_conversion=ConversionSummary(0, 0),
            baseline_conversion=ConversionSummary(0, 0),
            zone_visits=[],
            last_feed_at=None,
            queue_zone_keys=set(),
        )
        stale = next(r for r in results if r.anomaly_type == AnomalyType.STALE_FEED)
        assert stale.severity == AnomalySeverity.CRITICAL

    def test_stale_feed_warn(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[],
            baseline_queue=[],
            current_conversion=ConversionSummary(0, 0),
            baseline_conversion=ConversionSummary(0, 0),
            zone_visits=[],
            last_feed_at=PERIOD_END - timedelta(minutes=30),
            queue_zone_keys=set(),
            thresholds=AnomalyThresholds(
                stale_feed_warn_minutes=15,
                stale_feed_critical_minutes=60,
            ),
        )
        stale = next(r for r in results if r.anomaly_type == AnomalyType.STALE_FEED)
        assert stale.severity == AnomalySeverity.WARN

    def test_no_anomalies_when_healthy(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[ZoneVisitSummary("type:checkout", "checkout", 10)],
            baseline_queue=[ZoneVisitSummary("type:checkout", "checkout", 9)],
            current_conversion=ConversionSummary(entry_count=20, purchase_count=8),
            baseline_conversion=ConversionSummary(entry_count=20, purchase_count=8),
            zone_visits=[
                ZoneVisitSummary("type:browse", "browse", 80),
                ZoneVisitSummary("type:checkout", "checkout", 20),
            ],
            last_feed_at=PERIOD_END - timedelta(minutes=2),
            queue_zone_keys={"type:checkout"},
            thresholds=AnomalyThresholds(dead_zone_min_store_visits=50),
        )
        assert results == []

    def test_queue_spike_warn_severity(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[ZoneVisitSummary("type:checkout", "checkout", 12)],
            baseline_queue=[ZoneVisitSummary("type:checkout", "checkout", 8)],
            current_conversion=ConversionSummary(0, 0),
            baseline_conversion=ConversionSummary(0, 0),
            zone_visits=[],
            last_feed_at=PERIOD_END - timedelta(minutes=1),
            queue_zone_keys={"checkout"},
            thresholds=AnomalyThresholds(
                queue_spike_min_baseline_visits=5,
                queue_spike_ratio_warn=1.4,
                queue_spike_ratio_critical=3.0,
            ),
        )
        spike = next(r for r in results if r.anomaly_type == AnomalyType.QUEUE_SPIKE)
        assert spike.severity == AnomalySeverity.WARN

    def test_conversion_drop_critical(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[],
            baseline_queue=[],
            current_conversion=ConversionSummary(entry_count=20, purchase_count=2),
            baseline_conversion=ConversionSummary(entry_count=20, purchase_count=10),
            zone_visits=[],
            last_feed_at=PERIOD_END - timedelta(minutes=1),
            queue_zone_keys=set(),
            thresholds=AnomalyThresholds(conversion_min_entry=10, conversion_drop_pp_critical=0.25),
        )
        drop = next(r for r in results if r.anomaly_type == AnomalyType.CONVERSION_DROP)
        assert drop.severity == AnomalySeverity.CRITICAL

    def test_stale_feed_critical_after_sixty_minutes(self) -> None:
        results = AnomalyDetector.detect(
            store_id=STORE_ID,
            period_end=PERIOD_END,
            current_queue=[],
            baseline_queue=[],
            current_conversion=ConversionSummary(0, 0),
            baseline_conversion=ConversionSummary(0, 0),
            zone_visits=[],
            last_feed_at=PERIOD_END - timedelta(minutes=90),
            queue_zone_keys=set(),
            thresholds=AnomalyThresholds(
                stale_feed_warn_minutes=15,
                stale_feed_critical_minutes=60,
            ),
        )
        stale = next(r for r in results if r.anomaly_type == AnomalyType.STALE_FEED)
        assert stale.severity == AnomalySeverity.CRITICAL
