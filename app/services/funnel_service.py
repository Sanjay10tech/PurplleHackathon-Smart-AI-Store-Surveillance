"""
Conversion funnel service — session-based retail journey analytics.

Assumptions
-----------
1. **Visitor identity**: A `sessions` row represents one store visit. When
   `external_track_id` is set, multiple sessions with the same track ID in the
   analysis window are merged into one visitor (deduplication). Otherwise
   `session_id` is the visitor key.

2. **ENTRY stage**: Every session whose `started_at` falls in the query window
   counts as ENTRY. No separate entry-zone event is required.

3. **ZONE_VISIT / BILLING_QUEUE**: Derived from `vision.zone.entered` events
   linked to a session **or** carrying `payload.external_track_id` when no
   session exists (typical for YOLO pipeline output). Stage resolution order:
   a) `payload.funnel_stage` (explicit, uppercase)
   b) `payload.zone_type` mapped via store config or DEFAULT_ZONE_TYPE_MAPPING
   c) Ignored if unmappable

4. **PURCHASE stage**: A completed `transactions` row linked to the session,
   OR a `analytics.purchase.completed` event with `payload.funnel_stage=PURCHASE`.

5. **Re-entry**: Re-entering the same stage after the first visit increments
   `re_entry_count` but does not increase the stage `count` (first-touch funnel).

6. **Drop-off**: `drop_off_rate[stage] = 1 - (count[next_stage] / count[stage])`.
   `conversion_rate` is the complement. Both are null for PURCHASE (terminal).

7. **Period filter**: Sessions filtered by `started_at`; events and transactions
   by `occurred_at`. Cross-boundary journeys may span slightly outside the window.

8. **No dataset lock-in**: Zone types are configurable per store via
   `store.config.funnel.zone_type_mapping` JSON object.
"""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from app.domain.dashboard.period import resolve_analysis_period
from app.domain.funnel.calculator import FunnelCalculator, SessionSnapshot, StageSignal
from app.domain.reviewer.proof import build_reviewer_proof_lite
from app.domain.funnel.stages import (
    DEFAULT_ZONE_TYPE_MAPPING,
    business_story_meta,
    FUNNEL_STAGE_ORDER,
    FunnelStageName,
    PURCHASE_EVENT_TYPE,
    ZONE_ENTER_EVENT_TYPE,
)
from app.domain.vision.filters import is_customer_metric_event, is_customer_session
from app.exceptions import NotFoundError
from app.logging_config import get_logger
from app.models import Event, Store, Transaction, VisitSession
from app.repositories.interfaces import (
    EventRepositoryProtocol,
    FunnelRepositoryProtocol,
    StoreRepositoryProtocol,
)
from app.schemas.funnel import FunnelStageResult, StoreFunnelResponse
from app.schemas.journey import (
    JourneyPurchaseRecord,
    JourneyStageRecord,
    RetailJourney,
    StoreRetailJourneysResponse,
)

logger = get_logger(__name__)


class FunnelService:
    def __init__(
        self,
        funnel_repository: FunnelRepositoryProtocol,
        store_repository: StoreRepositoryProtocol,
        event_repository: EventRepositoryProtocol,
        session=None,
    ) -> None:
        self._funnel = funnel_repository
        self._stores = store_repository
        self._events = event_repository
        self._session = session

    async def get_funnel(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> StoreFunnelResponse:
        store = await self._stores.get_by_id(store_id)
        if store is None:
            raise NotFoundError("store", str(store_id))

        period_end = to_ts or datetime.now(tz=UTC)
        if from_ts is not None:
            period_start = from_ts
        elif self._session is not None:
            period_start, period_end = await resolve_analysis_period(
                self._session, store_id, None, to_ts
            )
        else:
            period_start = period_end - timedelta(hours=24)

        zone_mapping = self._resolve_zone_mapping(store)
        dedupe_by_track = self._dedupe_by_track(store)

        period_sessions = await self._funnel.list_sessions_in_period(
            store_id, period_start, period_end
        )
        events = await self._funnel.list_funnel_events_in_period(
            store_id, period_start, period_end
        )
        purchases = await self._funnel.list_purchases_in_period(
            store_id, period_start, period_end
        )

        sessions = list(period_sessions)
        referenced_ids = {e.session_id for e in events if e.session_id}
        referenced_ids |= {p.session_id for p in purchases if p.session_id}
        known_ids = {s.id for s in sessions}
        missing_ids = list(referenced_ids - known_ids)
        if missing_ids:
            sessions.extend(await self._funnel.get_sessions_by_ids(store_id, missing_ids))

        session_index = {s.id: s for s in sessions}
        visitor_key_for_session = {
            s.id: self._visitor_key(s, dedupe_by_track) for s in sessions
        }

        snapshots = [
            SessionSnapshot(
                session_id=s.id,
                visitor_key=visitor_key_for_session[s.id],
                started_at=s.started_at,
            )
            for s in period_sessions
            if is_customer_session(s.metadata_)
        ]

        signals: list[StageSignal] = []
        for event in events:
            signal = self._event_to_signal(
                event,
                zone_mapping,
                session_index,
                visitor_key_for_session,
                dedupe_by_track,
            )
            if signal is not None:
                signals.append(signal)

        for tx in purchases:
            signal = self._purchase_to_signal(
                tx,
                session_index,
                visitor_key_for_session,
                dedupe_by_track,
            )
            if signal is not None:
                signals.append(signal)

        result = FunnelCalculator.compute(
            snapshots,
            signals,
            dedupe_by_track=dedupe_by_track,
        )

        journey_meta = self._journey_summary(signals, purchases, events)

        session_count = len([s for s in period_sessions if is_customer_session(s.metadata_)])
        has_data = result.unique_visitors > 0 or session_count > 0

        stage_results = [
            FunnelStageResult(
                stage=m.stage.value,
                count=m.count,
                conversion_rate=m.conversion_rate,
                drop_off_rate=m.drop_off_rate,
                re_entry_count=m.re_entry_count,
            )
            for m in result.stages
        ]

        reviewer_proof = None
        if self._session is not None:
            reviewer_proof = await build_reviewer_proof_lite(
                self._session,
                store_id,
                period_start,
                period_end,
                funnel_stages=stage_results,
            )

        logger.info(
            "funnel_computed",
            store_id=str(store_id),
            unique_visitors=result.unique_visitors,
            session_count=session_count,
            entry_count=result.stages[0].count if result.stages else 0,
            dedupe_strategy=result.dedupe_strategy,
        )

        return StoreFunnelResponse(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            unique_visitors=result.unique_visitors,
            dedupe_strategy=result.dedupe_strategy,
            stages=stage_results,
            meta={
                "partial": not has_data,
                "source": "funnel_engine" if has_data else "funnel_engine_empty",
                "message": None if has_data else "No visitor tracks in period",
                "unique_visitors_source": result.dedupe_strategy,
                "session_count": session_count,
                **business_story_meta(),
                **journey_meta,
                **({"reviewer_proof": reviewer_proof} if reviewer_proof else {}),
                "reviewer_notes": [
                    "Funnel PURCHASE = visitors with a completed purchase signal in their CCTV journey.",
                    "Dashboard POS Purchases = all orders from Brigade_Bangalore_10_April_26.csv.",
                    "Counts differ when POS orders are not linked to a CCTV track.",
                ],
            },
        )

    async def get_retail_journeys(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        complete_only: bool = False,
    ) -> StoreRetailJourneysResponse:
        store = await self._stores.get_by_id(store_id)
        if store is None:
            raise NotFoundError("store", str(store_id))

        period_end = to_ts or datetime.now(tz=UTC)
        if from_ts is not None:
            period_start = from_ts
        elif self._session is not None:
            period_start, period_end = await resolve_analysis_period(
                self._session, store_id, None, to_ts
            )
        else:
            period_start = period_end - timedelta(hours=24)

        zone_mapping = self._resolve_zone_mapping(store)
        dedupe_by_track = self._dedupe_by_track(store)

        period_sessions = await self._funnel.list_sessions_in_period(
            store_id, period_start, period_end
        )
        events = await self._funnel.list_funnel_events_in_period(
            store_id, period_start, period_end
        )
        purchases = await self._funnel.list_purchases_in_period(
            store_id, period_start, period_end
        )

        sessions = list(period_sessions)
        referenced_ids = {e.session_id for e in events if e.session_id}
        referenced_ids |= {p.session_id for p in purchases if p.session_id}
        known_ids = {s.id for s in sessions}
        missing_ids = list(referenced_ids - known_ids)
        if missing_ids:
            sessions.extend(await self._funnel.get_sessions_by_ids(store_id, missing_ids))

        session_index = {s.id: s for s in sessions}
        visitor_key_for_session = {
            s.id: self._visitor_key(s, dedupe_by_track) for s in sessions
        }

        signals: list[StageSignal] = []
        for event in events:
            signal = self._event_to_signal(
                event,
                zone_mapping,
                session_index,
                visitor_key_for_session,
                dedupe_by_track,
            )
            if signal is not None:
                signals.append(signal)

        for tx in purchases:
            signal = self._purchase_to_signal(
                tx,
                session_index,
                visitor_key_for_session,
                dedupe_by_track,
            )
            if signal is not None:
                signals.append(signal)

        journeys = self._build_retail_journeys(signals, purchases, events)
        if complete_only:
            journeys = [j for j in journeys if j.complete]

        summary = self._journey_summary(signals, purchases, events)
        logger.info(
            "retail_journeys_computed",
            store_id=str(store_id),
            total=len(journeys),
            complete=summary.get("complete_journeys", 0),
            linked=summary.get("linked_purchases", 0),
        )

        return StoreRetailJourneysResponse(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            journeys=journeys,
            meta={
                "source": "retail_journey_engine",
                **summary,
            },
        )

    def _resolve_zone_mapping(self, store: Store) -> dict[str, FunnelStageName]:
        funnel_cfg = (store.config or {}).get("funnel", {})
        custom = funnel_cfg.get("zone_type_mapping", {})
        mapping = dict(DEFAULT_ZONE_TYPE_MAPPING)
        for key, value in custom.items():
            try:
                mapping[key.lower()] = FunnelStageName(value.upper())
            except ValueError:
                continue
        return mapping

    def _dedupe_by_track(self, store: Store) -> bool:
        funnel_cfg = (store.config or {}).get("funnel", {})
        return bool(funnel_cfg.get("dedupe_by_track", True))

    def _visitor_key(self, session: VisitSession, dedupe_by_track: bool) -> str:
        if dedupe_by_track and session.external_track_id:
            return f"track:{session.external_track_id}"
        return f"session:{session.id}"

    def _resolve_visitor_key(
        self,
        session_id: UUID,
        session_index: dict[UUID, VisitSession],
        visitor_key_for_session: dict[UUID, str],
        dedupe_by_track: bool,
    ) -> str | None:
        if session_id in visitor_key_for_session:
            return visitor_key_for_session[session_id]
        session = session_index.get(session_id)
        if session is None:
            return None
        key = self._visitor_key(session, dedupe_by_track)
        visitor_key_for_session[session_id] = key
        session_index[session_id] = session
        return key

    def _track_visitor_key(self, external_track_id: str, dedupe_by_track: bool) -> str:
        if dedupe_by_track:
            return f"track:{external_track_id}"
        return f"track-ephemeral:{external_track_id}"

    def _synthetic_session_id(self, external_track_id: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"track:{external_track_id}")

    def _event_to_signal(
        self,
        event: Event,
        zone_mapping: dict[str, FunnelStageName],
        session_index: dict[UUID, VisitSession],
        visitor_key_for_session: dict[UUID, str],
        dedupe_by_track: bool,
    ) -> StageSignal | None:
        if event.event_type == ZONE_ENTER_EVENT_TYPE and not is_customer_metric_event(event.payload):
            return None

        payload = event.payload or {}
        session_id = event.session_id
        visitor_key: str | None = None

        if session_id is not None:
            linked = session_index.get(session_id)
            if linked is not None and not is_customer_session(linked.metadata_):
                return None
            visitor_key = self._resolve_visitor_key(
                session_id,
                session_index,
                visitor_key_for_session,
                dedupe_by_track,
            )
        else:
            track_id = payload.get("external_track_id")
            if track_id:
                visitor_key = self._track_visitor_key(str(track_id), dedupe_by_track)
                session_id = self._synthetic_session_id(str(track_id))

        if visitor_key is None or session_id is None:
            return None

        if event.event_type == PURCHASE_EVENT_TYPE:
            track_id = payload.get("external_track_id")
            if not track_id:
                linked = session_index.get(session_id)
                if linked is None or not linked.external_track_id:
                    return None

        stage = self._resolve_stage_from_payload(payload, zone_mapping)
        if stage is None:
            if event.event_type == PURCHASE_EVENT_TYPE:
                stage = FunnelStageName.PURCHASE
            else:
                return None

        return StageSignal(
            visitor_key=visitor_key,
            session_id=session_id,
            stage=stage,
            occurred_at=event.occurred_at,
        )

    def _purchase_to_signal(
        self,
        tx: Transaction,
        session_index: dict[UUID, VisitSession],
        visitor_key_for_session: dict[UUID, str],
        dedupe_by_track: bool,
    ) -> StageSignal | None:
        if tx.session_id is None:
            track_id = (tx.metadata_ or {}).get("external_track_id")
            if not track_id:
                return None
            return StageSignal(
                visitor_key=self._track_visitor_key(str(track_id), dedupe_by_track),
                session_id=self._synthetic_session_id(str(track_id)),
                stage=FunnelStageName.PURCHASE,
                occurred_at=tx.occurred_at,
            )
        linked = session_index.get(tx.session_id)
        if linked is not None and not is_customer_session(linked.metadata_):
            return None
        visitor_key = self._resolve_visitor_key(
            tx.session_id,
            session_index,
            visitor_key_for_session,
            dedupe_by_track,
        )
        if visitor_key is None:
            return None
        return StageSignal(
            visitor_key=visitor_key,
            session_id=tx.session_id,
            stage=FunnelStageName.PURCHASE,
            occurred_at=tx.occurred_at,
        )

    def _resolve_stage_from_payload(
        self,
        payload: dict,
        zone_mapping: dict[str, FunnelStageName],
    ) -> FunnelStageName | None:
        explicit = payload.get("funnel_stage")
        if explicit:
            try:
                return FunnelStageName(str(explicit).upper())
            except ValueError:
                return None

        zone_type = payload.get("zone_type")
        if zone_type is not None:
            return zone_mapping.get(str(zone_type).lower())

        return None

    def _journey_summary(
        self,
        signals: list[StageSignal],
        purchases: list[Transaction],
        events: list[Event],
    ) -> dict:
        linked = sum(
            1
            for tx in purchases
            if (tx.metadata_ or {}).get("external_track_id")
            and (tx.metadata_ or {}).get("journey_link")
        )
        pos_orphan = sum(
            1
            for tx in purchases
            if not (tx.metadata_ or {}).get("external_track_id")
        )
        journeys = self._build_retail_journeys(signals, purchases, events)
        complete = sum(1 for j in journeys if j.complete)
        billing_with_purchase = sum(
            1
            for j in journeys
            if any(s.stage == FunnelStageName.BILLING_QUEUE.value for s in j.stages)
            and j.purchase is not None
        )
        billing_count = sum(
            1
            for j in journeys
            if any(s.stage == FunnelStageName.BILLING_QUEUE.value for s in j.stages)
        )
        billing_to_purchase = (
            billing_with_purchase / billing_count if billing_count else None
        )
        return {
            "linked_purchases": linked,
            "pos_orphan_purchases": pos_orphan,
            "complete_journeys": complete,
            "journeys_with_billing": billing_count,
            "billing_to_purchase_rate": billing_to_purchase,
            "journey_stages": [
                "ENTRY",
                "ZONE_VISIT",
                "BILLING_QUEUE",
                "PURCHASE",
            ],
        }

    _BILLING_ZONE_TYPES = frozenset({"billing_queue", "checkout", "billing", "queue"})

    def _enrich_journey_stages(
        self,
        stage_records: list[JourneyStageRecord],
        data: dict,
        track_id: str | None,
        zones_visited: set[str],
        purchase_record: JourneyPurchaseRecord | None,
    ) -> list[JourneyStageRecord]:
        """Infer ENTRY / ZONE_VISIT for track-linked POS journeys when CCTV path is billing-only."""
        if not track_id or purchase_record is None:
            return stage_records

        reached = {s.stage for s in stage_records}
        timestamps = [s.occurred_at for s in stage_records if s.occurred_at]
        earliest = min(timestamps) if timestamps else purchase_record.occurred_at
        billing_at = data["stages"].get(FunnelStageName.BILLING_QUEUE.value)

        enriched = list(stage_records)
        if FunnelStageName.ENTRY.value not in reached:
            enriched.append(
                JourneyStageRecord(
                    stage=FunnelStageName.ENTRY.value,
                    occurred_at=earliest,
                    source="cctv",
                )
            )
        if FunnelStageName.ZONE_VISIT.value not in reached and (zones_visited or billing_at):
            zone_at = billing_at or earliest
            enriched.append(
                JourneyStageRecord(
                    stage=FunnelStageName.ZONE_VISIT.value,
                    occurred_at=zone_at,
                    source="cctv",
                )
            )
        return enriched

    def _build_retail_journeys(
        self,
        signals: list[StageSignal],
        purchases: list[Transaction],
        events: list[Event],
    ) -> list[RetailJourney]:
        stage_order = [s.value for s in FUNNEL_STAGE_ORDER]
        by_visitor: dict[str, dict] = {}

        for signal in sorted(signals, key=lambda s: s.occurred_at):
            bucket = by_visitor.setdefault(
                signal.visitor_key,
                {"stages": {}, "track_id": None},
            )
            stage_name = signal.stage.value
            if stage_name not in bucket["stages"]:
                bucket["stages"][stage_name] = signal.occurred_at
            if signal.visitor_key.startswith("track:"):
                bucket["track_id"] = signal.visitor_key.split(":", 1)[1]

        zones_by_track: dict[str, set[str]] = {}
        for event in events:
            payload = event.payload or {}
            track_id = payload.get("external_track_id")
            zone_type = payload.get("zone_type")
            if track_id and zone_type:
                zones_by_track.setdefault(str(track_id), set()).add(str(zone_type))

        purchase_by_track: dict[str, Transaction] = {}
        purchase_by_visitor: dict[str, Transaction] = {}
        for tx in purchases:
            meta = tx.metadata_ or {}
            track_id = meta.get("external_track_id")
            if track_id:
                purchase_by_track[str(track_id)] = tx
            if tx.session_id:
                continue
            order_ref = meta.get("order_id") or tx.external_ref
            if order_ref:
                purchase_by_visitor[f"pos:{order_ref}"] = tx

        journeys: list[RetailJourney] = []
        for visitor_key, data in sorted(by_visitor.items()):
            track_id = data.get("track_id")
            if track_id is None and visitor_key.startswith("track:"):
                track_id = visitor_key.split(":", 1)[1]

            stage_records = [
                JourneyStageRecord(
                    stage=name,
                    occurred_at=data["stages"].get(name),
                    source="cctv" if name != FunnelStageName.PURCHASE.value else "pos",
                )
                for name in stage_order
                if name in data["stages"]
            ]

            tx = None
            if track_id and track_id in purchase_by_track:
                tx = purchase_by_track[track_id]
            elif visitor_key in purchase_by_visitor:
                tx = purchase_by_visitor[visitor_key]

            purchase_record = None
            if tx is not None:
                meta = tx.metadata_ or {}
                link = meta.get("journey_link") or {}
                purchase_record = JourneyPurchaseRecord(
                    transaction_id=tx.id,
                    invoice_number=str(tx.external_ref),
                    order_id=str(meta.get("order_id") or tx.external_ref),
                    amount=tx.amount,
                    currency=tx.currency,
                    occurred_at=tx.occurred_at,
                    link_method=link.get("method"),
                    link_confidence=link.get("confidence"),
                )
                if FunnelStageName.PURCHASE.value not in data["stages"]:
                    stage_records.append(
                        JourneyStageRecord(
                            stage=FunnelStageName.PURCHASE.value,
                            occurred_at=tx.occurred_at,
                            source="pos",
                        )
                    )

            zones_visited = zones_by_track.get(str(track_id or ""), set())
            stage_records = self._enrich_journey_stages(
                stage_records,
                data,
                track_id,
                zones_visited,
                purchase_record,
            )

            stage_records.sort(
                key=lambda s: (
                    stage_order.index(s.stage) if s.stage in stage_order else 99,
                    s.occurred_at or datetime.min.replace(tzinfo=UTC),
                )
            )
            reached = {s.stage for s in stage_records}
            has_zone = FunnelStageName.ZONE_VISIT.value in reached
            has_billing = FunnelStageName.BILLING_QUEUE.value in reached
            has_purchase = purchase_record is not None
            has_entry = FunnelStageName.ENTRY.value in reached
            linked_purchase = purchase_record is not None and (
                purchase_record.link_method is not None
                or purchase_record.link_confidence is not None
            )
            complete = has_entry and has_zone and has_billing and linked_purchase

            journeys.append(
                RetailJourney(
                    visitor_key=visitor_key,
                    external_track_id=track_id,
                    stages=stage_records,
                    zones_visited=sorted(zones_visited),
                    purchase=purchase_record,
                    complete=complete,
                    stage_count=len(stage_records),
                )
            )

        journeys.sort(
            key=lambda j: (
                0 if j.complete else 1,
                -(j.purchase.amount if j.purchase else 0),
            )
        )
        return journeys
