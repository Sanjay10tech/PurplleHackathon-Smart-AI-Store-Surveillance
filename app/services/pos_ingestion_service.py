"""
POS ingestion service — CSV → transactions → CCTV correlation → PURCHASE events.

Uses only real Brigade_Bangalore_10_April_26.csv data (ST1008).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.domain.funnel.pos_linker import (
    BillingTrackCandidate,
    PosLinkMode,
    PosTransactionCandidate,
    link_billing_to_pos,
)
from app.domain.funnel.stages import PURCHASE_EVENT_TYPE
from app.domain.pos.analytics import PosAggregates, aggregate_orders
from app.domain.pos.csv_parser import PosColumnAnalysis, PosOrder, parse_pos_csv
from app.logging_config import get_logger
from app.models import Event, Transaction, VisitSession

logger = get_logger(__name__)

BILLING_ZONE_TYPES = frozenset({"billing_queue", "checkout", "billing", "queue"})
DEFAULT_STORE_ID = UUID("00000000-0000-0000-0000-000000000101")
DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_CSV = Path("data/pos/Brigade_Bangalore_10_April_26.csv")


@dataclass
class PosIngestionResult:
    orders_parsed: int = 0
    transactions_inserted: int = 0
    transactions_skipped: int = 0
    purchase_events_created: int = 0
    sessions_linked: int = 0
    revenue_nmv: Decimal = Decimal("0")
    column_analysis: PosColumnAnalysis | None = None
    aggregates: PosAggregates | None = None
    source_file: str = ""
    errors: list[str] = field(default_factory=list)


class PosIngestionService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    async def ingest_store_pos(
        self,
        store_id: UUID,
        *,
        csv_path: Path | None = None,
        tenant_id: UUID = DEFAULT_TENANT_ID,
        replace_existing: bool = False,
        link_journeys: bool = True,
        emit_purchase_events: bool = True,
        store_code: str = "ST1008",
    ) -> PosIngestionResult:
        path = csv_path or Path(self._settings.pos_csv_path)
        result = PosIngestionResult(source_file=path.name)

        if not path.is_file():
            result.errors.append(f"POS CSV not found: {path}")
            return result

        orders, analysis = parse_pos_csv(path, store_code=store_code)
        result.orders_parsed = len(orders)
        result.column_analysis = analysis
        result.revenue_nmv = sum((o.nmv for o in orders), Decimal("0"))
        result.aggregates = aggregate_orders(orders)

        if replace_existing:
            await self._session.execute(
                delete(Transaction).where(Transaction.store_id == store_id)
            )
            await self._session.execute(
                delete(Event).where(
                    Event.store_id == store_id,
                    Event.event_type == PURCHASE_EVENT_TYPE,
                )
            )

        existing_refs = await self._existing_refs(store_id) if not replace_existing else set()

        for order in orders:
            ref = order.invoice_number
            if ref in existing_refs:
                result.transactions_skipped += 1
                continue

            top_brands = sorted(
                order.brand_totals.items(), key=lambda x: x[1], reverse=True
            )[:5]
            top_categories = sorted(
                order.category_totals.items(), key=lambda x: x[1], reverse=True
            )[:5]

            self._session.add(
                Transaction(
                    store_id=store_id,
                    session_id=None,
                    external_ref=ref,
                    amount=order.nmv,
                    currency="INR",
                    status="completed",
                    occurred_at=order.occurred_at,
                    metadata_={
                        "source": "pos_csv",
                        "source_file": path.name,
                        "order_id": order.order_id,
                        "customer_name": order.customer_name,
                        "customer_number": order.customer_number,
                        "gmv": str(order.gmv),
                        "total_amount": str(order.total_amount),
                        "line_count": order.line_count,
                        "salesperson": order.salesperson,
                        "offer_name": order.offer_name,
                        "brands": [
                            {"brand_name": b, "nmv": str(v)} for b, v in top_brands
                        ],
                        "categories": [
                            {"category": c, "nmv": str(v)} for c, v in top_categories
                        ],
                    },
                )
            )
            result.transactions_inserted += 1
            existing_refs.add(ref)

        await self._session.flush()

        if link_journeys:
            result.sessions_linked = await self.recorrelate_journeys(store_id)

        if emit_purchase_events:
            result.purchase_events_created = await self._emit_purchase_events(
                store_id, tenant_id, path.name
            )

        await self._session.commit()

        logger.info(
            "pos_ingestion_complete",
            store_id=str(store_id),
            orders=result.orders_parsed,
            inserted=result.transactions_inserted,
            linked=result.sessions_linked,
            purchase_events=result.purchase_events_created,
            revenue=str(result.revenue_nmv),
        )
        return result

    async def _existing_refs(self, store_id: UUID) -> set[str]:
        rows = await self._session.execute(
            select(Transaction.external_ref).where(Transaction.store_id == store_id)
        )
        return {r for r in rows.scalars() if r}

    async def recorrelate_journeys(
        self,
        store_id: UUID,
        *,
        mode: PosLinkMode = PosLinkMode.AUTO,
        window_minutes: int = 20,
        relink_existing: bool = False,
    ) -> int:
        """Match billing-queue CCTV tracks to POS orders (idempotent)."""
        return await self._correlate_with_cctv(
            store_id,
            mode=mode,
            window_minutes=window_minutes,
            relink_existing=relink_existing,
        )

    async def sync_purchase_event_tracks(self, store_id: UUID) -> int:
        """Backfill external_track_id on analytics purchase events from linked transactions."""
        tx_rows = await self._session.execute(
            select(Transaction).where(
                Transaction.store_id == store_id,
                Transaction.status == "completed",
            )
        )
        tx_by_order: dict[str, Transaction] = {}
        for tx in tx_rows.scalars():
            meta = tx.metadata_ or {}
            order_id = str(meta.get("order_id") or tx.external_ref or tx.id)
            tx_by_order[order_id] = tx

        event_rows = await self._session.execute(
            select(Event).where(
                Event.store_id == store_id,
                Event.event_type == PURCHASE_EVENT_TYPE,
            )
        )
        updated = 0
        for event in event_rows.scalars():
            payload = dict(event.payload or {})
            order_id = str(payload.get("order_id") or "")
            tx = tx_by_order.get(order_id)
            if tx is None:
                continue
            meta = tx.metadata_ or {}
            track_id = meta.get("external_track_id")
            if not track_id:
                continue
            if payload.get("external_track_id") == track_id and event.session_id == tx.session_id:
                continue
            payload["external_track_id"] = track_id
            event.payload = payload
            if tx.session_id is not None:
                event.session_id = tx.session_id
            updated += 1
        return updated

    async def _correlate_with_cctv(
        self,
        store_id: UUID,
        *,
        mode: PosLinkMode = PosLinkMode.AUTO,
        window_minutes: int = 20,
        relink_existing: bool = False,
    ) -> int:
        event_rows = await self._session.execute(
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

        tx_rows = await self._session.execute(
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
            if meta.get("external_track_id") and not relink_existing:
                continue
            if relink_existing and meta.get("external_track_id"):
                meta.pop("external_track_id", None)
                meta.pop("journey_link", None)
                tx.metadata_ = meta
            pos_candidates.append(
                PosTransactionCandidate(
                    transaction_id=str(tx.id),
                    order_id=str(meta.get("order_id") or tx.external_ref),
                    invoice_number=str(tx.external_ref),
                    occurred_at=tx.occurred_at,
                    amount=str(tx.amount),
                )
            )

        matches = link_billing_to_pos(
            billing_candidates,
            pos_candidates,
            mode=mode,
            window_minutes=window_minutes,
        )

        tx_by_id = {str(tx.id): tx for tx in transactions}
        linked = 0
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
            tx.metadata_ = meta

            session_id = await self._resolve_session_for_track(
                store_id, match.external_track_id
            )
            if session_id is not None:
                tx.session_id = session_id
            linked += 1

        return linked

    async def _resolve_session_for_track(
        self, store_id: UUID, external_track_id: str
    ) -> UUID | None:
        stmt = (
            select(VisitSession)
            .where(
                VisitSession.store_id == store_id,
                VisitSession.external_track_id == external_track_id,
            )
            .order_by(VisitSession.started_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return row.id if row else None

    async def _emit_purchase_events(
        self,
        store_id: UUID,
        tenant_id: UUID,
        source_file: str,
    ) -> int:
        existing_keys = set(
            (await self._session.execute(
                select(Event.idempotency_key).where(
                    Event.store_id == store_id,
                    Event.event_type == PURCHASE_EVENT_TYPE,
                )
            )).scalars()
        )

        tx_rows = await self._session.execute(
            select(Transaction).where(
                Transaction.store_id == store_id,
                Transaction.status == "completed",
            )
        )
        created = 0
        for tx in tx_rows.scalars():
            meta = dict(tx.metadata_ or {})
            order_id = str(meta.get("order_id") or tx.external_ref or tx.id)
            idem = f"pos-purchase-{order_id}"
            if idem in existing_keys:
                continue

            payload: dict = {
                "funnel_stage": "PURCHASE",
                "order_id": order_id,
                "invoice_number": tx.external_ref,
                "amount": str(tx.amount),
                "currency": tx.currency,
                "source": "pos_csv",
                "source_file": source_file,
                "line_count": meta.get("line_count"),
                "brands": meta.get("brands") or [],
                "categories": meta.get("categories") or [],
            }
            track_id = meta.get("external_track_id")
            if track_id:
                payload["external_track_id"] = track_id

            self._session.add(
                Event(
                    store_id=store_id,
                    tenant_id=tenant_id,
                    session_id=tx.session_id,
                    event_type=PURCHASE_EVENT_TYPE,
                    schema_version=self._settings.event_schema_version,
                    aggregate_type="purchase",
                    aggregate_id=uuid5(NAMESPACE_URL, f"pos-{order_id}"),
                    payload=payload,
                    correlation_id=f"pos-ingest-{order_id}",
                    idempotency_key=idem,
                    occurred_at=tx.occurred_at,
                )
            )
            existing_keys.add(idem)
            created += 1
        return created
