"""
Store anomaly detection service — on-read rule engine.

Assumptions
-----------
1. **Detection modes**: Computes QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, and
   STALE_FEED on each request. Persisted rows in `anomalies` are merged when present.

2. **Baseline window**: Previous period of equal length immediately before the
   query window (e.g. last 24h vs prior 24h).

3. **Queue zones**: Identified by `store.config.anomalies.queue_zone_keys` or
   default zone types: checkout, billing_queue, queue, billing.

4. **Conversion drop**: Compares ENTRY→PURCHASE rate between current and baseline
   using the same funnel engine inputs (sessions + zone/purchase events).

5. **Dead zone**: Zone visit count below 5% of peak zone traffic with sufficient
   store-wide traffic (≥20 visits, ≥2 zones).

6. **Stale feed**: No `vision.frame.processed` or `vision.zone.entered` within
   configured minutes (default WARN=15, CRITICAL=60).

7. **Severity**: INFO, WARN, CRITICAL with operator-facing `suggested_action`.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.dashboard.period import resolve_analysis_period
from app.domain.anomaly.detector import (
    AnomalyDetector,
    AnomalyThresholds,
    ConversionSummary,
    ZoneVisitSummary,
)
from app.domain.anomaly.types import AnomalySeverity
from app.domain.heatmap.constants import DEFAULT_QUEUE_ZONE_TYPES
from app.domain.vision.filters import is_customer_metric_event
from app.exceptions import NotFoundError
from app.logging_config import get_logger
from app.models import Store
from app.repositories.interfaces import (
    AnomalyRepositoryProtocol,
    EventRepositoryProtocol,
    FunnelRepositoryProtocol,
    HeatmapRepositoryProtocol,
    StoreRepositoryProtocol,
)
from app.schemas.anomalies import AnomalyItem, StoreAnomaliesResponse
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService

logger = get_logger(__name__)

SEVERITY_RANK = {
    "CRITICAL": 0,
    "critical": 0,
    "WARN": 1,
    "warning": 1,
    "INFO": 2,
    "info": 2,
}


class AnomalyService:
    def __init__(
        self,
        heatmap_repository: HeatmapRepositoryProtocol,
        funnel_repository: FunnelRepositoryProtocol,
        store_repository: StoreRepositoryProtocol,
        anomaly_repository: AnomalyRepositoryProtocol,
        event_repository: EventRepositoryProtocol,
        session=None,
    ) -> None:
        self._heatmap_repo = heatmap_repository
        self._funnel_repo = funnel_repository
        self._stores = store_repository
        self._anomalies = anomaly_repository
        self._session = session
        self._heatmap = HeatmapService(heatmap_repository, store_repository)
        self._funnel = FunnelService(
            funnel_repository, store_repository, event_repository, session=session
        )

    async def get_anomalies(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> StoreAnomaliesResponse:
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
        window = period_end - period_start
        baseline_end = period_start
        baseline_start = baseline_end - window

        thresholds = self._resolve_thresholds(store)
        queue_zone_keys = self._resolve_queue_zones(store)

        current_zones = await self._zone_summaries(store_id, period_start, period_end)
        baseline_zones = await self._zone_summaries(store_id, baseline_start, baseline_end)

        current_conversion = await self._conversion_summary(store_id, period_start, period_end)
        baseline_conversion = await self._conversion_summary(
            store_id, baseline_start, baseline_end
        )

        last_feed_at = await self._heatmap_repo.get_latest_feed_timestamp(
            store_id, before=period_end
        )

        computed = AnomalyDetector.detect(
            store_id=store_id,
            period_end=period_end,
            current_queue=current_zones,
            baseline_queue=baseline_zones,
            current_conversion=current_conversion,
            baseline_conversion=baseline_conversion,
            zone_visits=current_zones,
            last_feed_at=last_feed_at,
            queue_zone_keys=queue_zone_keys,
            thresholds=thresholds,
        )

        persisted = await self._anomalies.list_by_store(
            store_id,
            from_ts=period_start,
            to_ts=period_end,
        )

        items = self._merge_results(computed, persisted)

        logger.info(
            "anomalies_computed",
            store_id=str(store_id),
            computed=len(computed),
            persisted=len(persisted),
            total=len(items),
        )

        reviewer_proof = None
        if self._session is not None:
            reviewer_proof = {
                "checklist_url": "/reviewer",
                "note": "Authoritative 8-check proof lives at GET /reviewer.",
            }

        return StoreAnomaliesResponse(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            items=items,
            meta={
                "partial": len(items) == 0 and last_feed_at is None,
                "source": "anomaly_engine" if items else "anomaly_engine_empty",
                "computed_count": len(computed),
                "persisted_count": len(persisted),
                "baseline_start": baseline_start.isoformat(),
                "baseline_end": baseline_end.isoformat(),
                **({"reviewer_proof": reviewer_proof} if reviewer_proof else {}),
            },
        )

    async def _zone_summaries(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[ZoneVisitSummary]:
        events = await self._heatmap_repo.list_zone_events_in_period(store_id, from_ts, to_ts)
        counts: dict[str, dict] = {}
        for event in events:
            if event.event_type != "vision.zone.entered":
                continue
            if not is_customer_metric_event(event.payload):
                continue
            zone_key, zone_label, _ = HeatmapService._resolve_zone(event.payload)
            if zone_key is None:
                continue
            bucket = counts.setdefault(zone_key, {"label": zone_label, "count": 0})
            bucket["count"] += 1

        return [
            ZoneVisitSummary(zone_key=key, zone_label=b["label"], visit_count=b["count"])
            for key, b in sorted(counts.items())
        ]

    async def _conversion_summary(
        self,
        store_id: UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> ConversionSummary:
        result = await self._funnel.get_funnel(store_id, from_ts=from_ts, to_ts=to_ts)
        stages = {s.stage: s for s in result.stages}
        return ConversionSummary(
            entry_count=stages.get("ENTRY").count if stages.get("ENTRY") else 0,
            purchase_count=stages.get("PURCHASE").count if stages.get("PURCHASE") else 0,
        )

    def _merge_results(self, computed, persisted) -> list[AnomalyItem]:
        items: list[AnomalyItem] = [
            AnomalyItem(
                id=a.id,
                anomaly_type=a.anomaly_type.value,
                severity=a.severity.value,
                detected_at=a.detected_at,
                message=a.message,
                suggested_action=a.suggested_action,
                context=a.context,
                source="computed",
            )
            for a in computed
        ]

        computed_types = {a.anomaly_type.value for a in computed}
        for row in persisted:
            normalized_severity = self._normalize_severity(row.severity)
            anomaly_type = row.anomaly_type.upper()
            if anomaly_type in computed_types:
                continue
            items.append(
                AnomalyItem(
                    id=row.id,
                    anomaly_type=anomaly_type,
                    severity=normalized_severity,
                    detected_at=row.detected_at,
                    message=row.message,
                    suggested_action=str(
                        (row.context or {}).get("suggested_action", "Review anomaly details and take appropriate action.")
                    ),
                    context=row.context or {},
                    source="persisted",
                )
            )

        items.sort(
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 99),
                item.detected_at,
            )
        )
        return items

    @staticmethod
    def _normalize_severity(severity: str) -> str:
        mapping = {
            "critical": AnomalySeverity.CRITICAL.value,
            "warning": AnomalySeverity.WARN.value,
            "warn": AnomalySeverity.WARN.value,
            "info": AnomalySeverity.INFO.value,
        }
        return mapping.get(severity.lower(), severity.upper())

    @staticmethod
    def _resolve_thresholds(store: Store) -> AnomalyThresholds:
        cfg = (store.config or {}).get("anomalies", {})
        return AnomalyThresholds(
            queue_spike_ratio_warn=float(cfg.get("queue_spike_ratio_warn", 1.5)),
            queue_spike_ratio_critical=float(cfg.get("queue_spike_ratio_critical", 2.5)),
            queue_spike_min_baseline_visits=int(cfg.get("queue_spike_min_baseline_visits", 5)),
            conversion_drop_pp_warn=float(cfg.get("conversion_drop_pp_warn", 0.15)),
            conversion_drop_pp_critical=float(cfg.get("conversion_drop_pp_critical", 0.30)),
            conversion_min_entry=int(cfg.get("conversion_min_entry", 10)),
            dead_zone_ratio=float(cfg.get("dead_zone_ratio", 0.05)),
            dead_zone_min_store_visits=int(cfg.get("dead_zone_min_store_visits", 20)),
            dead_zone_min_zones=int(cfg.get("dead_zone_min_zones", 2)),
            stale_feed_warn_minutes=int(cfg.get("stale_feed_warn_minutes", 15)),
            stale_feed_critical_minutes=int(cfg.get("stale_feed_critical_minutes", 60)),
        )

    @staticmethod
    def _resolve_queue_zones(store: Store) -> set[str]:
        cfg = (store.config or {}).get("anomalies", {})
        custom = cfg.get("queue_zone_keys")
        if custom:
            return {str(k).lower() for k in custom}
        return {f"type:{z}" for z in DEFAULT_QUEUE_ZONE_TYPES} | set(DEFAULT_QUEUE_ZONE_TYPES)
