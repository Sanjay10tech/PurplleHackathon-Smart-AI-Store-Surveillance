#!/usr/bin/env python3
"""Link POS transactions to CCTV billing-queue tracks for funnel journey proof."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")
BILLING_ZONE_TYPES = {"billing_queue", "checkout", "billing", "queue"}


async def link_pos_journeys(
    store_id: UUID,
    *,
    mode: str = "auto",
    window_minutes: int = 20,
    dry_run: bool = False,
    clear_existing: bool = False,
) -> dict:
    import os

    from sqlalchemy import select

    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton
    from app.domain.funnel.pos_linker import (
        BillingTrackCandidate,
        PosLinkMode,
        PosTransactionCandidate,
        link_billing_to_pos,
    )
    from app.models import Event, Transaction

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = url
    reset_engine_singleton()

    link_mode = PosLinkMode(mode)
    engine = create_engine()
    sf = create_session_factory(engine)
    stats = {
        "billing_tracks": 0,
        "pos_orders": 0,
        "linked": 0,
        "cleared": 0,
        "matches": [],
    }

    async with sf() as session:
        event_rows = await session.execute(
            select(Event).where(
                Event.store_id == store_id,
                Event.event_type == "vision.zone.entered",
            )
        )
        billing_by_track: dict[str, datetime] = {}
        billing_counts: dict[str, int] = {}
        for event in event_rows.scalars():
            payload = event.payload or {}
            zone_type = str(payload.get("zone_type") or "").lower()
            track_id = payload.get("external_track_id")
            if not track_id or zone_type not in BILLING_ZONE_TYPES:
                continue
            track_key = str(track_id)
            billing_counts[track_key] = billing_counts.get(track_key, 0) + 1
            prev = billing_by_track.get(track_key)
            if prev is None or event.occurred_at < prev:
                billing_by_track[track_key] = event.occurred_at

        tx_rows = await session.execute(
            select(Transaction).where(
                Transaction.store_id == store_id,
                Transaction.status == "completed",
            ).order_by(Transaction.occurred_at)
        )
        transactions = list(tx_rows.scalars())

        billing_candidates = [
            BillingTrackCandidate(
                external_track_id=track_id,
                first_billing_at=first_at,
                billing_event_count=billing_counts.get(track_id, 1),
            )
            for track_id, first_at in sorted(billing_by_track.items(), key=lambda x: x[1])
        ]

        pos_candidates: list[PosTransactionCandidate] = []
        for tx in transactions:
            meta = dict(tx.metadata_ or {})
            if clear_existing and meta.get("journey_link"):
                meta.pop("external_track_id", None)
                meta.pop("journey_link", None)
                tx.metadata_ = meta
                stats["cleared"] += 1
            if meta.get("external_track_id") and not clear_existing:
                continue
            pos_candidates.append(
                PosTransactionCandidate(
                    transaction_id=str(tx.id),
                    order_id=str(meta.get("order_id") or tx.external_ref),
                    invoice_number=str(tx.external_ref),
                    occurred_at=tx.occurred_at,
                    amount=str(tx.amount),
                )
            )

        stats["billing_tracks"] = len(billing_candidates)
        stats["pos_orders"] = len(pos_candidates)

        matches = link_billing_to_pos(
            billing_candidates,
            pos_candidates,
            mode=link_mode,
            window_minutes=window_minutes,
        )

        tx_by_id = {str(tx.id): tx for tx in transactions}
        for match in matches:
            tx = tx_by_id.get(match.transaction_id)
            if tx is None:
                continue
            meta = dict(tx.metadata_ or {})
            meta["external_track_id"] = match.external_track_id
            meta["journey_link"] = {
                "method": match.link_method,
                "confidence": match.confidence,
                "billing_at": match.billing_at.isoformat(),
                "delta_seconds": match.delta_seconds,
                "linked_at": datetime.now(tz=UTC).isoformat(),
            }
            if not dry_run:
                tx.metadata_ = meta
            stats["linked"] += 1
            stats["matches"].append(
                {
                    "track_id": match.external_track_id[-12:],
                    "invoice": match.invoice_number,
                    "order_id": match.order_id,
                    "method": match.link_method,
                    "confidence": match.confidence,
                }
            )

        if not dry_run:
            await session.commit()

    await dispose_engine()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Link POS purchases to CCTV billing tracks")
    parser.add_argument("--store-id", type=UUID, default=DEMO_STORE_ID)
    parser.add_argument(
        "--mode",
        choices=("auto", "time_window", "sequential"),
        default="auto",
        help="Matching strategy (auto tries time window then sequential fallback)",
    )
    parser.add_argument("--window-minutes", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clear", action="store_true", help="Clear existing journey links before matching")
    args = parser.parse_args()

    stats = asyncio.run(
        link_pos_journeys(
            args.store_id,
            mode=args.mode,
            window_minutes=args.window_minutes,
            dry_run=args.dry_run,
            clear_existing=args.clear,
        )
    )
    print(f"Billing tracks: {stats['billing_tracks']}")
    print(f"POS orders (unlinked): {stats['pos_orders']}")
    print(f"Linked: {stats['linked']}")
    for match in stats["matches"]:
        print(
            f"  track ...{match['track_id']} -> {match['invoice']} "
            f"({match['method']}, conf={match['confidence']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
