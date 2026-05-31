from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.dashboard.coverage import get_event_coverage
from app.domain.dashboard.kpi_queries import (
    aggregate_top_brands,
    aggregate_top_categories,
    count_completed_purchases,
    count_customer_sessions,
    count_linked_purchases,
    count_pipeline_events,
    count_reentry_events,
    count_session_exits,
    count_store_entry_events,
    count_store_exit_events,
    get_store_last_event_at,
    sum_completed_revenue,
)
from app.domain.dashboard.period import resolve_analysis_period
from app.exceptions import NotFoundError
from app.logging_config import get_logger
from app.repositories.interfaces import StoreRepositoryProtocol
from app.schemas.common import PaginatedMeta
from app.schemas.dashboard import (
    DashboardKpiCard,
    DashboardProvenance,
    DashboardReviewerEvidence,
    ReviewerHeadline,
    StoreDashboardSummaryResponse,
)
from app.schemas.pos import PosInsights, PosLinkageEvidence, PosRankItem
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService

logger = get_logger(__name__)

NO_DATA = "No Data Available"


class DashboardService:
    def __init__(
        self,
        session: AsyncSession,
        store_repository: StoreRepositoryProtocol,
        funnel_service: FunnelService,
        heatmap_service: HeatmapService,
        analytics_service: AnalyticsService,
        anomaly_service: AnomalyService,
    ) -> None:
        self._session = session
        self._stores = store_repository
        self._funnel = funnel_service
        self._heatmap = heatmap_service
        self._analytics = analytics_service
        self._anomalies = anomaly_service

    async def _analysis_period(
        self,
        store_id: UUID,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> tuple[datetime, datetime]:
        return await resolve_analysis_period(
            self._session, store_id, from_ts, to_ts
        )

    @staticmethod
    def _stage(funnel, name: str):
        for stage in funnel.stages:
            if stage.stage == name:
                return stage
        return None

    @staticmethod
    def _weighted_avg_dwell(zones) -> float | None:
        total_samples = 0
        weighted_sum = 0.0
        for zone in zones:
            count = int(getattr(zone, "dwell_sample_count", 0) or 0)
            dwell = getattr(zone, "avg_dwell_seconds", None)
            if count > 0 and dwell is not None:
                total_samples += count
                weighted_sum += float(dwell) * count
        if total_samples == 0:
            return None
        return weighted_sum / total_samples

    @staticmethod
    def _feed_status(last_event_at: datetime | None) -> str:
        if last_event_at is None:
            return "unknown"
        settings = get_settings()
        minutes = (datetime.now(tz=UTC) - last_event_at.astimezone(UTC)).total_seconds() / 60.0
        if minutes >= settings.health_stale_feed_minutes:
            return "stale"
        return "fresh"

    @staticmethod
    def _detection_evidence(
        coverage: dict[str, object],
        last_event_at: datetime | None,
    ) -> str | None:
        if not coverage.get("total_events_in_period"):
            return None
        mode = coverage.get("detector_mode") or "unknown"
        lineage = coverage.get("processing_lineage") or "ingested_events"
        videos = coverage.get("source_videos") or []
        video_txt = ", ".join(str(v) for v in videos) if videos else "none logged"
        last_txt = (
            last_event_at.astimezone(UTC).isoformat()
            if last_event_at
            else "never"
        )
        return (
            f"Detector: {mode} · Lineage: {lineage} · "
            f"Source videos: {video_txt} · Last event: {last_txt}"
        )

    async def get_summary(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> StoreDashboardSummaryResponse:
        store = await self._stores.get_by_id(store_id)
        if store is None:
            raise NotFoundError("store", str(store_id))

        period_start, period_end = await self._analysis_period(store_id, from_ts, to_ts)

        funnel, heatmap, metrics, anomalies = await self._gather(
            store_id, period_start, period_end
        )
        coverage = await get_event_coverage(
            self._session, store_id, period_start, period_end
        )

        entry_stage = self._stage(funnel, "ENTRY")
        billing_stage = self._stage(funnel, "BILLING_QUEUE")
        purchase_stage = self._stage(funnel, "PURCHASE")

        purchase_stage = self._stage(funnel, "PURCHASE")
        purchase_count_db = await count_completed_purchases(
            self._session, store_id, period_start, period_end
        )
        linked_purchases = await count_linked_purchases(
            self._session, store_id, period_start, period_end
        )
        revenue = await sum_completed_revenue(
            self._session, store_id, period_start, period_end
        )
        top_brands_raw = await aggregate_top_brands(
            self._session, store_id, period_start, period_end
        )
        top_categories_raw = await aggregate_top_categories(
            self._session, store_id, period_start, period_end
        )

        store_entries = await count_store_entry_events(
            self._session, store_id, period_start, period_end
        )
        store_exits = await count_store_exit_events(
            self._session, store_id, period_start, period_end
        )
        session_exits = await count_session_exits(
            self._session, store_id, period_start, period_end
        )
        customer_sessions = await count_customer_sessions(
            self._session, store_id, period_start, period_end
        )
        reentry_events = await count_reentry_events(
            self._session, store_id, period_start, period_end
        )
        pipeline_events = await count_pipeline_events(
            self._session, store_id, period_start, period_end
        )
        last_event_at = await get_store_last_event_at(self._session, store_id)

        funnel_reentries = sum(s.re_entry_count for s in funnel.stages)
        re_entries = max(reentry_events, funnel_reentries)

        entry_count = entry_stage.count if entry_stage else 0
        unique_visitors = funnel.unique_visitors
        entries = max(entry_count, store_entries, customer_sessions)
        exits = max(store_exits, session_exits)
        funnel_purchase = purchase_stage.count if purchase_stage else 0
        purchase_count = max(funnel_purchase, purchase_count_db)
        avg_basket = float(revenue / purchase_count_db) if purchase_count_db > 0 else None
        conversion = (
            min(linked_purchases, entries) / entries
            if entries > 0 and linked_purchases > 0
            else None
        )

        queue_depth = billing_stage.count if billing_stage else 0
        anomaly_count = len(anomalies.items)
        session_count = int(funnel.meta.get("session_count", 0)) or customer_sessions
        data_confidence = str(heatmap.meta.get("data_confidence", "LOW"))
        feed_status = self._feed_status(last_event_at)

        has_data = (
            unique_visitors > 0
            or entry_count > 0
            or pipeline_events > 0
            or purchase_count_db > 0
        )

        outside = int(coverage.get("events_outside_period") or 0)
        partial_message = None
        if not has_data:
            partial_message = NO_DATA
        elif outside > 0:
            partial_message = (
                f"{outside} older event(s) exist outside the current window — "
                "period starts at first ingested event"
            )

        frames_analyzed = int(coverage.get("frames_logged") or 0)
        source_videos = list(coverage.get("source_videos") or [])

        kpis = [
            self._kpi(
                "unique_visitors", "Unique Visitors", unique_visitors,
                str(unique_visitors) if has_data else NO_DATA,
                source="funnel dedupe (sessions + track_id)",
            ),
            self._kpi(
                "total_entries", "Entries", entries,
                str(entries) if has_data else NO_DATA,
                source="funnel ENTRY stage (sessions.started_at)",
            ),
            self._kpi(
                "total_exits", "Exits", exits,
                str(exits) if has_data else NO_DATA,
                source="events[is_store_exit] + sessions.ended_at",
            ),
            self._kpi(
                "re_entries", "Re-Entries", re_entries,
                str(re_entries) if has_data else NO_DATA,
                source="payload.is_reentry + funnel.re_entry_count",
            ),
            self._kpi(
                "customer_sessions", "Sessions", session_count,
                str(session_count) if has_data else NO_DATA,
                source="sessions (customer)",
            ),
            self._kpi(
                "conversion_rate", "Linked Conversion (CCTV↔POS)", conversion,
                f"{conversion * 100:.1f}%" if conversion is not None else NO_DATA,
                unit="%",
                source="linked POS purchases / CCTV entries",
            ),
            self._kpi(
                "revenue", "Revenue (NMV)", float(revenue),
                f"₹{float(revenue):,.2f}" if purchase_count_db > 0 else NO_DATA,
                unit="INR",
                source="transactions.amount (POS CSV NMV)",
            ),
            self._kpi(
                "purchases", "POS Purchases (CSV)", purchase_count_db,
                str(purchase_count_db) if purchase_count_db > 0 else NO_DATA,
                source="Brigade_Bangalore_10_April_26.csv",
            ),
            self._kpi(
                "average_basket_value", "Avg Basket Value", avg_basket,
                f"₹{avg_basket:,.2f}" if avg_basket is not None else NO_DATA,
                unit="INR",
                source="revenue / purchase_count",
            ),
            self._kpi(
                "queue_depth", "Queue Depth", queue_depth,
                str(queue_depth) if has_data else NO_DATA,
                source="funnel.BILLING_QUEUE",
            ),
            self._kpi(
                "anomalies", "Anomaly Count", anomaly_count,
                str(anomaly_count) if has_data else NO_DATA,
                source="anomaly_engine",
            ),
        ]

        provenance = DashboardProvenance(
            dedupe_strategy=funnel.dedupe_strategy,
            data_confidence=data_confidence,
            feed_status=feed_status,
            last_event_at=last_event_at,
            pipeline_events=pipeline_events,
            zones_tracked=len(heatmap.zones),
            layout_mapped=bool(heatmap.meta.get("layout_mapped")),
            detector_mode=coverage.get("detector_mode"),
            source_videos=source_videos,
            processing_lineage=coverage.get("processing_lineage"),
        )

        reviewer_evidence = DashboardReviewerEvidence(
            videos_processed=len(source_videos),
            source_videos=source_videos,
            frames_analyzed=frames_analyzed,
            events_generated=pipeline_events,
            last_ingestion_at=last_event_at,
            detector_mode=coverage.get("detector_mode"),
            processing_lineage=coverage.get("processing_lineage"),
            detection_evidence=self._detection_evidence(coverage, last_event_at),
        )

        linkage_rate = (
            linked_purchases / purchase_count_db
            if purchase_count_db > 0 and linked_purchases > 0
            else None
        )
        pos_insights = PosInsights(
            source_file="Brigade_Bangalore_10_April_26.csv",
            revenue_nmv=float(revenue),
            purchase_count=purchase_count_db,
            linked_purchases=linked_purchases,
            average_basket_value=avg_basket,
            conversion_rate=conversion,
            top_brands=[
                PosRankItem(name=b["brand_name"], revenue=b["revenue"])
                for b in top_brands_raw
            ],
            top_categories=[
                PosRankItem(name=c["category"], revenue=c["revenue"])
                for c in top_categories_raw
            ],
            column_summary={
                "transaction_key": "order_id → invoice_number",
                "revenue_field": "NMV",
                "timestamp_fields": ["order_date", "order_time"],
                "brand_field": "brand_name",
                "category_fields": ["dep_name", "sub_category"],
            },
            linkage=PosLinkageEvidence(
                linked_purchases=linked_purchases,
                pos_purchases=purchase_count_db,
                linkage_rate=linkage_rate,
                explanation=(
                    f"{linked_purchases} of {purchase_count_db} POS orders matched a CCTV "
                    "billing-zone track within ±20 minutes (CAM 5 queue zone). "
                    "Funnel PURCHASE counts journey completion; POS Purchases counts all CSV orders."
                ),
            ),
        )

        footnotes: list[str] = []
        if purchase_count_db > 0 and funnel_purchase != purchase_count_db:
            footnotes.append(
                f"Funnel PURCHASE ({funnel_purchase}) = CCTV-linked journeys; "
                f"POS Purchases ({purchase_count_db}) = all CSV orders."
            )
        if unique_visitors != entries:
            footnotes.append(
                f"Unique visitors ({unique_visitors}) dedupe by track ID; "
                f"entries ({entries}) count store threshold crossings."
            )
        if feed_status == "stale" and has_data:
            footnotes.append(
                "Vision feed is stale (batch ingest). Metrics below are from PostgreSQL, not live cameras."
            )

        reviewer_headline = ReviewerHeadline(
            cctv_videos=f"{len(source_videos)}/5",
            vision_events=pipeline_events,
            entries=entries,
            exits=exits,
            re_entries=re_entries,
            unique_visitors=unique_visitors,
            funnel_purchase=funnel_purchase,
            pos_purchases=purchase_count_db,
            pos_revenue_inr=float(revenue),
            linked_purchases=linked_purchases,
            feed_status=feed_status,
            feed_note=footnotes[-1] if feed_status == "stale" and has_data else None,
            footnotes=footnotes,
        )

        logger.info(
            "dashboard_summary_computed",
            store_id=str(store_id),
            unique_visitors=unique_visitors,
            entries=entries,
            pipeline_events=pipeline_events,
            pos_purchases=purchase_count_db,
            revenue=float(revenue),
        )

        return StoreDashboardSummaryResponse(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            last_refreshed_at=datetime.now(tz=UTC),
            kpis=kpis,
            reviewer_evidence=reviewer_evidence,
            reviewer_headline=reviewer_headline,
            provenance=provenance,
            funnel_stages=funnel.stages,
            pos_insights=pos_insights if purchase_count_db > 0 else None,
            meta=PaginatedMeta(
                partial=not has_data,
                source="dashboard_engine" if has_data else "dashboard_engine_empty",
                message=partial_message,
            ),
        )

    async def _gather(self, store_id: UUID, period_start: datetime, period_end: datetime):
        funnel = await self._funnel.get_funnel(
            store_id, from_ts=period_start, to_ts=period_end
        )
        heatmap = await self._heatmap.get_heatmap(
            store_id, from_ts=period_start, to_ts=period_end
        )
        metrics = await self._analytics.get_metrics(
            store_id, from_ts=period_start, to_ts=period_end
        )
        anomalies = await self._anomalies.get_anomalies(
            store_id, from_ts=period_start, to_ts=period_end
        )
        return funnel, heatmap, metrics, anomalies

    @staticmethod
    def _kpi(
        key: str,
        label: str,
        value: float | int | str | None,
        formatted: str,
        *,
        unit: str | None = None,
        source: str,
        available: bool = True,
    ) -> DashboardKpiCard:
        return DashboardKpiCard(
            key=key,
            label=label,
            value=value,
            formatted=formatted,
            unit=unit,
            available=available,
            source=source,
            category="overview",
            business_value="",
        )
