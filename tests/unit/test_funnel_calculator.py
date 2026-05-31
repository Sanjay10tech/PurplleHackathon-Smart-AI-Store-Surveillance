# PROMPT:
# Generate complete pytest suite — pure FunnelCalculator unit tests.
#
# CHANGES MADE:
# - Drop-off math, re-entry counting, track dedupe, and empty-period behavior.

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.funnel.calculator import FunnelCalculator, SessionSnapshot, StageSignal
from app.domain.funnel.stages import FunnelStageName


def _session(visitor: str, offset_min: int = 0) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=uuid.uuid4(),
        visitor_key=visitor,
        started_at=datetime(2026, 5, 30, 12, offset_min, tzinfo=UTC),
    )


def _signal(
    visitor: str,
    stage: FunnelStageName,
    offset_min: int,
    session_id: uuid.UUID | None = None,
) -> StageSignal:
    return StageSignal(
        visitor_key=visitor,
        session_id=session_id or uuid.uuid4(),
        stage=stage,
        occurred_at=datetime(2026, 5, 30, 12, offset_min, tzinfo=UTC),
    )


class TestFunnelCalculator:
    def test_full_funnel_with_drop_off(self) -> None:
        sessions = [_session("v1"), _session("v2"), _session("v3"), _session("v4")]
        signals = [
            _signal("v1", FunnelStageName.ZONE_VISIT, 5),
            _signal("v1", FunnelStageName.BILLING_QUEUE, 10),
            _signal("v1", FunnelStageName.PURCHASE, 15),
            _signal("v2", FunnelStageName.ZONE_VISIT, 6),
            _signal("v2", FunnelStageName.BILLING_QUEUE, 11),
            _signal("v3", FunnelStageName.ZONE_VISIT, 7),
        ]
        result = FunnelCalculator.compute(sessions, signals, dedupe_by_track=True)

        assert result.unique_visitors == 4
        stages = {s.stage: s for s in result.stages}
        assert stages[FunnelStageName.ENTRY].count == 4
        assert stages[FunnelStageName.ZONE_VISIT].count == 3
        assert stages[FunnelStageName.BILLING_QUEUE].count == 2
        assert stages[FunnelStageName.PURCHASE].count == 1

        assert stages[FunnelStageName.ENTRY].conversion_rate == 0.75
        assert stages[FunnelStageName.ENTRY].drop_off_rate == 0.25
        assert stages[FunnelStageName.ZONE_VISIT].conversion_rate == pytest.approx(0.6667)
        assert stages[FunnelStageName.BILLING_QUEUE].conversion_rate == 0.5
        assert stages[FunnelStageName.PURCHASE].conversion_rate is None

    def test_re_entry_increments_but_not_count(self) -> None:
        sessions = [_session("v1")]
        signals = [
            _signal("v1", FunnelStageName.ZONE_VISIT, 5),
            _signal("v1", FunnelStageName.ZONE_VISIT, 20),
            _signal("v1", FunnelStageName.ZONE_VISIT, 35),
        ]
        result = FunnelCalculator.compute(sessions, signals, dedupe_by_track=True)
        zone = next(s for s in result.stages if s.stage == FunnelStageName.ZONE_VISIT)
        assert zone.count == 1
        assert zone.re_entry_count == 2

    def test_visitor_dedupe_by_track_key(self) -> None:
        sessions = [
            SessionSnapshot(uuid.uuid4(), "track:42", datetime(2026, 5, 30, 12, 0, tzinfo=UTC)),
            SessionSnapshot(uuid.uuid4(), "track:42", datetime(2026, 5, 30, 13, 0, tzinfo=UTC)),
        ]
        signals = [
            _signal("track:42", FunnelStageName.ZONE_VISIT, 10),
            _signal("track:42", FunnelStageName.PURCHASE, 20),
        ]
        result = FunnelCalculator.compute(sessions, signals, dedupe_by_track=True)
        assert result.unique_visitors == 1
        assert result.stages[0].count == 1
        assert result.stages[1].count == 1
        assert result.stages[3].count == 1

    def test_empty_period(self) -> None:
        result = FunnelCalculator.compute([], [], dedupe_by_track=True)
        assert result.unique_visitors == 0
        assert all(s.count == 0 for s in result.stages)

    def test_conversion_capped_when_downstream_exceeds_upstream(self) -> None:
        """Purchase without billing queue must not produce conversion > 100%."""
        sessions = [_session("v1"), _session("v2")]
        signals = [
            _signal("v1", FunnelStageName.PURCHASE, 5),
            _signal("v2", FunnelStageName.ZONE_VISIT, 6),
        ]
        result = FunnelCalculator.compute(sessions, signals, dedupe_by_track=True)
        entry = next(s for s in result.stages if s.stage == FunnelStageName.ENTRY)
        purchase = next(s for s in result.stages if s.stage == FunnelStageName.PURCHASE)
        assert purchase.count == 1
        assert entry.conversion_rate == 0.5
        self._assert_rates_bounded(result)

    def test_zero_purchases_empty_funnel_stages(self) -> None:
        sessions = [_session("v1")]
        signals = [_signal("v1", FunnelStageName.ZONE_VISIT, 5)]
        result = FunnelCalculator.compute(sessions, signals, dedupe_by_track=True)
        purchase = next(s for s in result.stages if s.stage == FunnelStageName.PURCHASE)
        assert purchase.count == 0
        self._assert_rates_bounded(result)

    def test_reentry_does_not_inflate_conversion(self) -> None:
        sessions = [_session("v1"), _session("v2")]
        signals = [
            _signal("v1", FunnelStageName.ZONE_VISIT, 5),
            _signal("v1", FunnelStageName.ZONE_VISIT, 20),
            _signal("v2", FunnelStageName.ZONE_VISIT, 6),
        ]
        result = FunnelCalculator.compute(sessions, signals, dedupe_by_track=True)
        zone = next(s for s in result.stages if s.stage == FunnelStageName.ZONE_VISIT)
        assert zone.count == 2
        assert zone.re_entry_count == 1
        self._assert_rates_bounded(result)

    def test_duplicate_sessions_same_track_deduped(self) -> None:
        sessions = [
            SessionSnapshot(uuid.uuid4(), "track:99", datetime(2026, 5, 30, 12, 0, tzinfo=UTC)),
            SessionSnapshot(uuid.uuid4(), "track:99", datetime(2026, 5, 30, 13, 0, tzinfo=UTC)),
        ]
        result = FunnelCalculator.compute(sessions, [], dedupe_by_track=True)
        assert result.unique_visitors == 1
        assert result.stages[0].count == 1
        self._assert_rates_bounded(result)

    def test_sequential_conversion_ignores_skipped_upstream_visitors(self) -> None:
        """Downstream-only tracks must not inflate upstream conversion."""
        sessions = [_session("v1"), _session("v2")]
        signals = [
            _signal("v1", FunnelStageName.ZONE_VISIT, 5),
            _signal("zone-only-a", FunnelStageName.ZONE_VISIT, 6),
            _signal("zone-only-b", FunnelStageName.ZONE_VISIT, 7),
        ]
        result = FunnelCalculator.compute(sessions, signals, dedupe_by_track=True)
        entry = next(s for s in result.stages if s.stage == FunnelStageName.ENTRY)
        zone = next(s for s in result.stages if s.stage == FunnelStageName.ZONE_VISIT)
        assert entry.count == 4
        assert zone.count == 3
        assert entry.conversion_rate == 0.75
        assert entry.drop_off_rate == 0.25
        self._assert_rates_bounded(result)

    @staticmethod
    def _assert_rates_bounded(result) -> None:
        for stage in result.stages:
            rate = stage.conversion_rate
            if rate is not None:
                assert 0.0 <= rate <= 1.0, f"{stage.stage} conversion_rate={rate}"
            drop = stage.drop_off_rate
            if drop is not None:
                assert 0.0 <= drop <= 1.0, f"{stage.stage} drop_off_rate={drop}"
