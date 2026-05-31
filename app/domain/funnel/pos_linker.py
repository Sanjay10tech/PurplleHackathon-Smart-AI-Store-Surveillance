"""
POS ↔ CCTV journey linker — pure matching logic (no I/O).

Links billing-queue vision tracks to POS transactions so PURCHASE attaches to the
same visitor_key as ZONE_VISIT and BILLING_QUEUE in the funnel engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class PosLinkMode(StrEnum):
    TIME_WINDOW = "time_window"
    SEQUENTIAL = "sequential"
    AUTO = "auto"


@dataclass(frozen=True)
class BillingTrackCandidate:
    external_track_id: str
    first_billing_at: datetime
    billing_event_count: int = 1


@dataclass(frozen=True)
class PosTransactionCandidate:
    transaction_id: str
    order_id: str
    invoice_number: str
    occurred_at: datetime
    amount: str


@dataclass(frozen=True)
class PosLinkMatch:
    external_track_id: str
    transaction_id: str
    order_id: str
    invoice_number: str
    billing_at: datetime
    purchase_at: datetime
    link_method: str
    delta_seconds: float
    confidence: float


def link_billing_to_pos(
    billing_tracks: list[BillingTrackCandidate],
    pos_orders: list[PosTransactionCandidate],
    *,
    mode: PosLinkMode = PosLinkMode.AUTO,
    window_minutes: int = 20,
    time_offset: timedelta = timedelta(0),
) -> list[PosLinkMatch]:
    """
    Match billing-queue tracks to POS orders.

    ``time_offset`` shifts POS timestamps before comparison (e.g. align store-local
    POS day to CCTV pilot ingest window).
    """
    if not billing_tracks or not pos_orders:
        return []

    billing_sorted = sorted(billing_tracks, key=lambda b: b.first_billing_at)
    pos_sorted = sorted(pos_orders, key=lambda p: p.occurred_at)

    if mode == PosLinkMode.SEQUENTIAL:
        return _link_sequential(billing_sorted, pos_sorted)

    time_matches = _link_time_window(
        billing_sorted,
        pos_sorted,
        window_minutes=window_minutes,
        time_offset=time_offset,
    )
    if mode == PosLinkMode.TIME_WINDOW or len(time_matches) == len(billing_sorted):
        return time_matches

    matched_tx_ids = {m.transaction_id for m in time_matches}
    remaining_billing = [
        b
        for b in billing_sorted
        if not any(m.external_track_id == b.external_track_id for m in time_matches)
    ]
    remaining_pos = [p for p in pos_sorted if p.transaction_id not in matched_tx_ids]
    sequential = _link_sequential(remaining_billing, remaining_pos)
    return time_matches + sequential


def _link_time_window(
    billing_tracks: list[BillingTrackCandidate],
    pos_orders: list[PosTransactionCandidate],
    *,
    window_minutes: int,
    time_offset: timedelta,
) -> list[PosLinkMatch]:
    window = timedelta(minutes=window_minutes)
    used_pos: set[str] = set()
    matches: list[PosLinkMatch] = []

    for track in billing_tracks:
        best: PosTransactionCandidate | None = None
        best_delta = float("inf")
        for pos in pos_orders:
            if pos.transaction_id in used_pos:
                continue
            adjusted = pos.occurred_at + time_offset
            delta = abs((adjusted - track.first_billing_at).total_seconds())
            if delta <= window.total_seconds() and delta < best_delta:
                best = pos
                best_delta = delta
        if best is None:
            continue
        used_pos.add(best.transaction_id)
        confidence = max(0.0, 1.0 - (best_delta / window.total_seconds()))
        matches.append(
            PosLinkMatch(
                external_track_id=track.external_track_id,
                transaction_id=best.transaction_id,
                order_id=best.order_id,
                invoice_number=best.invoice_number,
                billing_at=track.first_billing_at,
                purchase_at=best.occurred_at,
                link_method="time_window",
                delta_seconds=best_delta,
                confidence=round(confidence, 3),
            )
        )
    return matches


def _link_sequential(
    billing_tracks: list[BillingTrackCandidate],
    pos_orders: list[PosTransactionCandidate],
) -> list[PosLinkMatch]:
    matches: list[PosLinkMatch] = []
    for track, pos in zip(billing_tracks, pos_orders, strict=False):
        delta = abs((pos.occurred_at - track.first_billing_at).total_seconds())
        matches.append(
            PosLinkMatch(
                external_track_id=track.external_track_id,
                transaction_id=pos.transaction_id,
                order_id=pos.order_id,
                invoice_number=pos.invoice_number,
                billing_at=track.first_billing_at,
                purchase_at=pos.occurred_at,
                link_method="sequential",
                delta_seconds=delta,
                confidence=0.75,
            )
        )
    return matches
