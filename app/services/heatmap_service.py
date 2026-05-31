"""
Zone heatmap service — visit frequency, dwell, and normalized scores.

Assumptions
-----------
1. **Zone identity**: `payload.zone_id` is preferred; falls back to `payload.zone_type`.
   Keys are prefixed (`id:` / `type:`) to avoid collisions.

2. **Visit counting**: Each `vision.zone.entered` event counts as one visit for that zone.

3. **Dwell time**: Taken from `vision.zone.exited` payload (`dwell_ms` or `dwell_seconds`).
   Enter-only visits contribute to visit count but not dwell averages.

4. **Normalization**: Min-max scaling (0–1) across zones in the response period.
   Single-zone or equal values yield 1.0 for non-zero metrics.

5. **Data confidence** (per zone):
   - HIGH: ≥5 visits and dwell on ≥50% of visits
   - MEDIUM: ≥3 visits with partial dwell coverage
   - LOW: fewer than 3 visits or no dwell samples

6. **Store layout**: When `store.config.heatmap.layout_file` is set (or the
   default Brigade Road YAML exists), camera zone events are remapped to
   physical layout zones from `data/store_layout/brigade_road_layout.yaml`.

7. **Period filter**: Events filtered by `occurred_at` within `[from, to]`.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.heatmap.calculator import HeatmapCalculator, RawZoneVisit
from app.domain.heatmap.constants import ZONE_ENTER_EVENT_TYPE, ZONE_EXIT_EVENT_TYPE
from app.domain.heatmap.layout_mapping import get_layout_for_store
from app.domain.vision.filters import is_customer_metric_event
from app.domain.dashboard.period import resolve_analysis_period
from app.exceptions import NotFoundError
from app.logging_config import get_logger
from app.models import Event, Store
from app.repositories.interfaces import HeatmapRepositoryProtocol, StoreRepositoryProtocol
from app.schemas.heatmap import HeatmapZoneCell, StoreHeatmapResponse

logger = get_logger(__name__)


class HeatmapService:
    def __init__(
        self,
        heatmap_repository: HeatmapRepositoryProtocol,
        store_repository: StoreRepositoryProtocol,
        session=None,
    ) -> None:
        self._heatmap = heatmap_repository
        self._stores = store_repository
        self._session = session

    async def get_heatmap(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> StoreHeatmapResponse:
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

        cfg = (store.config or {}).get("heatmap", {})
        min_high = int(cfg.get("min_samples_high", 5))
        min_medium = int(cfg.get("min_samples_medium", 3))

        events = await self._heatmap.list_zone_events_in_period(
            store_id, period_start, period_end
        )
        visits, camera_ids = self._build_visits(events)
        layout = self._load_layout(store, store_id)
        if layout is not None:
            visits = layout.remap_visits(visits, camera_zone_ids=camera_ids)
        result = HeatmapCalculator.compute(
            visits,
            min_samples_high=min_high,
            min_samples_medium=min_medium,
        )

        overall_confidence = self._overall_confidence(result.zones)

        logger.info(
            "heatmap_computed",
            store_id=str(store_id),
            zone_count=len(result.zones),
            total_visits=result.total_visits,
            overall_confidence=overall_confidence,
        )

        return StoreHeatmapResponse(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            zones=[
                HeatmapZoneCell(
                    zone_key=z.zone_key,
                    zone_label=z.zone_label,
                    visit_count=z.visit_count,
                    avg_dwell_seconds=z.avg_dwell_seconds,
                    dwell_sample_count=z.dwell_sample_count,
                    normalized_visit_score=z.normalized_visit_score,
                    normalized_dwell_score=z.normalized_dwell_score,
                    data_confidence=z.data_confidence,
                    layout_section=self._layout_section(layout, z.zone_key),
                )
                for z in result.zones
            ],
            meta={
                "partial": result.total_visits == 0,
                "source": "heatmap_engine" if result.total_visits else "heatmap_engine_empty",
                "data_confidence": overall_confidence,
                "total_visits": result.total_visits,
                "zones_with_dwell": result.zones_with_dwell,
                "message": None if result.total_visits else "No zone events in period",
                "layout_source": layout.source_file if layout else None,
                "layout_version": layout.layout_version if layout else None,
                "layout_mapped": layout is not None,
            },
        )

    def _load_layout(self, store: Store, store_id: UUID):
        cfg = (store.config or {}).get("heatmap", {})
        if cfg.get("use_layout") is False:
            return None
        layout_file = cfg.get("layout_file")
        path = str(layout_file) if layout_file else None
        layout = get_layout_for_store(str(store_id), path)
        if layout is None:
            return None
        if cfg.get("use_layout") is True or layout.store_id == str(store_id):
            return layout
        return None

    @staticmethod
    def _layout_section(layout, zone_key: str) -> str | None:
        if layout is None or not zone_key.startswith("layout:"):
            return None
        zone_id = zone_key.removeprefix("layout:")
        zone = layout.zones_by_id.get(zone_id)
        if zone is None:
            return None
        section = layout.sections.get(zone.section, {})
        return section.get("label", zone.section)

    def _build_visits(self, events: list[Event]) -> tuple[list[RawZoneVisit], list[str | None]]:
        visits: list[RawZoneVisit] = []
        camera_ids: list[str | None] = []

        for event in events:
            if not is_customer_metric_event(event.payload):
                continue
            zone_key, zone_label, camera_zone_id = self._resolve_zone(event.payload)
            if zone_key is None:
                continue

            if event.event_type == ZONE_ENTER_EVENT_TYPE:
                visits.append(
                    RawZoneVisit(
                        zone_key=zone_key,
                        zone_label=zone_label,
                        is_enter=True,
                    )
                )
                camera_ids.append(camera_zone_id)
            elif event.event_type == ZONE_EXIT_EVENT_TYPE:
                dwell = self._extract_dwell_seconds(event.payload)
                if dwell is not None:
                    visits.append(
                        RawZoneVisit(
                            zone_key=zone_key,
                            zone_label=zone_label,
                            is_enter=False,
                            dwell_seconds=dwell,
                        )
                    )
                    camera_ids.append(camera_zone_id)
        return visits, camera_ids

    @staticmethod
    def _resolve_zone(payload: dict) -> tuple[str, str, str | None] | tuple[None, None, None]:
        zone_id = payload.get("zone_id")
        if zone_id:
            label = str(payload.get("zone_name") or payload.get("zone_type") or zone_id)
            return f"id:{zone_id}", label, str(zone_id)

        zone_type = payload.get("zone_type")
        if zone_type:
            return f"type:{str(zone_type).lower()}", str(zone_type), None

        return None, None, None

    @staticmethod
    def _extract_dwell_seconds(payload: dict) -> float | None:
        if "dwell_ms" in payload:
            return float(payload["dwell_ms"]) / 1000.0
        if "dwell_seconds" in payload:
            return float(payload["dwell_seconds"])
        return None

    @staticmethod
    def _overall_confidence(zones: list) -> str:
        if not zones:
            return "LOW"
        levels = {z.data_confidence for z in zones}
        if levels == {"HIGH"}:
            return "HIGH"
        if "LOW" in levels and len(levels) == 1:
            return "LOW"
        if "HIGH" in levels:
            return "MEDIUM"
        return "LOW" if levels == {"LOW"} else "MEDIUM"
