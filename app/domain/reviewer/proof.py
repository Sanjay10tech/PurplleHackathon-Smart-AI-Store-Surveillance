"""Reviewer proof checklist — no service-layer imports (avoids circular deps)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dashboard.coverage import get_event_coverage
from app.domain.dashboard.kpi_queries import (
    count_customer_sessions,
    count_linked_purchases,
    count_pipeline_events,
    count_session_exits,
    count_store_entry_events,
    count_store_exit_events,
)


def _check(label: str, passed: bool, evidence: str) -> dict[str, object]:
    return {
        "label": label,
        "passed": passed,
        "evidence": evidence,
    }


async def build_reviewer_proof_lite(
    session: AsyncSession,
    store_id: UUID,
    period_start: datetime,
    period_end: datetime,
    *,
    funnel_stages: list | None = None,
    heatmap_zones: list | None = None,
) -> dict[str, object]:
    """Lightweight proof for embedding in API meta (no extra funnel/heatmap queries)."""
    coverage = await get_event_coverage(session, store_id, period_start, period_end)
    source_videos = list(coverage.get("source_videos") or [])
    pipeline_events = await count_pipeline_events(
        session, store_id, period_start, period_end
    )
    store_entries = await count_store_entry_events(
        session, store_id, period_start, period_end
    )
    store_exits = await count_store_exit_events(
        session, store_id, period_start, period_end
    )
    session_count = await count_customer_sessions(
        session, store_id, period_start, period_end
    )
    session_exits = await count_session_exits(
        session, store_id, period_start, period_end
    )
    linked_purchases = await count_linked_purchases(
        session, store_id, period_start, period_end
    )

    re_entries = 0
    funnel_counts: dict[str, int] = {}
    if funnel_stages:
        for stage in funnel_stages:
            funnel_counts[stage.stage] = stage.count
            re_entries += stage.re_entry_count

    effective_entries = max(
        store_entries,
        funnel_counts.get("ENTRY", 0),
        session_count,
    )
    effective_exits = max(store_exits, session_exits)
    funnel_purchase = funnel_counts.get("PURCHASE", 0)

    heatmap_zone_count = len(heatmap_zones or [])
    heatmap_visits = sum(z.visit_count for z in (heatmap_zones or []))

    checks = [
        _check(
            "5 CCTV videos processed",
            len(source_videos) >= 5,
            f"{len(source_videos)}/5 cameras: {', '.join(source_videos) or 'none'}",
        ),
        _check(
            "Vision events generated",
            pipeline_events > 0,
            f"{pipeline_events} events · detector={coverage.get('detector_mode') or 'unknown'}",
        ),
        _check(
            "Entries detected",
            effective_entries > 0,
            f"events={store_entries} sessions={session_count} funnel ENTRY={funnel_counts.get('ENTRY', 0)}",
        ),
        _check(
            "Exits detected",
            effective_exits > 0,
            f"events={store_exits} session_end={session_exits}",
        ),
        _check(
            "Re-entry tracking",
            re_entries > 0,
            f"{re_entries} re-entries",
        ),
        _check(
            "Conversion logic",
            effective_entries > 0
            and funnel_purchase <= effective_entries
            and (linked_purchases > 0 or funnel_counts.get("BILLING_QUEUE", 0) > 0),
            f"entries={effective_entries} funnel PURCHASE={funnel_purchase} linked POS={linked_purchases}",
        ),
        _check(
            "Funnel engine",
            len(funnel_counts) >= 4,
            " → ".join(f"{k}={v}" for k, v in funnel_counts.items()) or "no stages",
        ),
        _check(
            "Heatmap zones",
            heatmap_zone_count > 0 and heatmap_visits > 0,
            f"{heatmap_zone_count} zones · {heatmap_visits} visits",
        ),
    ]
    passed = sum(1 for c in checks if c["passed"])

    return {
        "checks_passed": passed,
        "checks_total": len(checks),
        "ready_for_review": passed >= 6,
        "checks": checks,
        "summary": {
            "videos_processed": len(source_videos),
            "source_videos": source_videos,
            "events_generated": pipeline_events,
            "entries": effective_entries,
            "exits": effective_exits,
            "sessions": session_count,
            "linked_purchases": linked_purchases,
            "re_entries": re_entries,
            "funnel": funnel_counts,
            "heatmap_zones": heatmap_zone_count,
            "detector_mode": coverage.get("detector_mode"),
        },
    }
