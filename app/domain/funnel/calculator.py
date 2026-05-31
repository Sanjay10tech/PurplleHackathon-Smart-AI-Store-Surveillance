from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.funnel.stages import FUNNEL_STAGE_ORDER, FunnelStageName


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: UUID
    visitor_key: str
    started_at: datetime


@dataclass(frozen=True)
class StageSignal:
    """A single funnel stage signal tied to a visitor journey."""

    visitor_key: str
    session_id: UUID
    stage: FunnelStageName
    occurred_at: datetime


@dataclass
class FunnelStageMetrics:
    stage: FunnelStageName
    count: int
    conversion_rate: float | None = None
    drop_off_rate: float | None = None
    re_entry_count: int = 0


@dataclass
class FunnelComputationResult:
    unique_visitors: int
    stages: list[FunnelStageMetrics]
    dedupe_strategy: str


@dataclass
class VisitorStageState:
    reached: set[FunnelStageName] = field(default_factory=set)
    re_entries: dict[FunnelStageName, int] = field(default_factory=dict)
    stage_first_at: dict[FunnelStageName, datetime] = field(default_factory=dict)


class FunnelCalculator:
    """
    Pure funnel computation — no I/O.

    Assumptions documented in module docstring of funnel_service.py.
    """

    @classmethod
    def compute(
        cls,
        sessions: list[SessionSnapshot],
        stage_signals: list[StageSignal],
        *,
        dedupe_by_track: bool = True,
    ) -> FunnelComputationResult:
        visitors: dict[str, VisitorStageState] = {}

        for session in sessions:
            state = visitors.setdefault(session.visitor_key, VisitorStageState())
            cls._mark_stage(state, FunnelStageName.ENTRY, session.started_at)

        sorted_signals = sorted(stage_signals, key=lambda s: s.occurred_at)
        for signal in sorted_signals:
            state = visitors.setdefault(signal.visitor_key, VisitorStageState())
            cls._apply_signal(state, signal)

        # Tracks with zone/billing signals but no explicit entry (short YOLO samples)
        for state in visitors.values():
            if FunnelStageName.ENTRY not in state.reached and state.reached:
                earliest = min(state.stage_first_at.values())
                cls._mark_stage(state, FunnelStageName.ENTRY, earliest)

        stage_counts: dict[FunnelStageName, int] = {s: 0 for s in FUNNEL_STAGE_ORDER}
        re_entry_totals: dict[FunnelStageName, int] = {s: 0 for s in FUNNEL_STAGE_ORDER}

        for state in visitors.values():
            for stage in FUNNEL_STAGE_ORDER:
                if stage in state.reached:
                    stage_counts[stage] += 1
                re_entry_totals[stage] += state.re_entries.get(stage, 0)

        metrics = cls._build_metrics(stage_counts, re_entry_totals, visitors)

        return FunnelComputationResult(
            unique_visitors=len(visitors),
            stages=metrics,
            dedupe_strategy="external_track_id" if dedupe_by_track else "session_id",
        )

    @classmethod
    def _apply_signal(cls, state: VisitorStageState, signal: StageSignal) -> None:
        if signal.stage in state.reached:
            state.re_entries[signal.stage] = state.re_entries.get(signal.stage, 0) + 1
        else:
            cls._mark_stage(state, signal.stage, signal.occurred_at)

    @classmethod
    def _mark_stage(
        cls,
        state: VisitorStageState,
        stage: FunnelStageName,
        occurred_at: datetime,
    ) -> None:
        if stage not in state.reached:
            state.reached.add(stage)
            state.stage_first_at[stage] = occurred_at

    @classmethod
    def _build_metrics(
        cls,
        counts: dict[FunnelStageName, int],
        re_entries: dict[FunnelStageName, int],
        visitors: dict[str, VisitorStageState],
    ) -> list[FunnelStageMetrics]:
        metrics: list[FunnelStageMetrics] = []
        for i, stage in enumerate(FUNNEL_STAGE_ORDER):
            count = counts[stage]
            conversion_rate: float | None = None
            drop_off_rate: float | None = None
            if i + 1 < len(FUNNEL_STAGE_ORDER):
                next_stage = FUNNEL_STAGE_ORDER[i + 1]
                if count > 0:
                    sequential = sum(
                        1
                        for state in visitors.values()
                        if stage in state.reached and next_stage in state.reached
                    )
                    conversion_rate = min(1.0, round(sequential / count, 4))
                    drop_off_rate = round(1.0 - conversion_rate, 4)
            metrics.append(
                FunnelStageMetrics(
                    stage=stage,
                    count=count,
                    conversion_rate=conversion_rate,
                    drop_off_rate=drop_off_rate,
                    re_entry_count=re_entries[stage],
                )
            )
        return metrics
