from enum import StrEnum


class FunnelStageName(StrEnum):
    ENTRY = "ENTRY"
    ZONE_VISIT = "ZONE_VISIT"
    BILLING_QUEUE = "BILLING_QUEUE"
    PURCHASE = "PURCHASE"


FUNNEL_STAGE_ORDER: list[FunnelStageName] = [
    FunnelStageName.ENTRY,
    FunnelStageName.ZONE_VISIT,
    FunnelStageName.BILLING_QUEUE,
    FunnelStageName.PURCHASE,
]

# Default zone_type → funnel stage mapping (overridable via store.config.funnel.zone_type_mapping)
DEFAULT_ZONE_TYPE_MAPPING: dict[str, FunnelStageName] = {
    "entry": FunnelStageName.ENTRY,
    "entrance": FunnelStageName.ENTRY,
    "entry_threshold": FunnelStageName.ENTRY,
    "browse": FunnelStageName.ZONE_VISIT,
    "browse_skincare": FunnelStageName.ZONE_VISIT,
    "browse_cosmetics": FunnelStageName.ZONE_VISIT,
    "aisle": FunnelStageName.ZONE_VISIT,
    "display": FunnelStageName.ZONE_VISIT,
    "zone": FunnelStageName.ZONE_VISIT,
    "promo_island": FunnelStageName.ZONE_VISIT,
    "consultation": FunnelStageName.ZONE_VISIT,
    "billing_queue": FunnelStageName.BILLING_QUEUE,
    "checkout": FunnelStageName.BILLING_QUEUE,
    "queue": FunnelStageName.BILLING_QUEUE,
    "billing": FunnelStageName.BILLING_QUEUE,
}

ZONE_ENTER_EVENT_TYPE = "vision.zone.entered"
PURCHASE_EVENT_TYPE = "analytics.purchase.completed"

# Business-facing labels for dashboard, docs, and API meta
STAGE_BUSINESS_LABELS: dict[FunnelStageName, str] = {
    FunnelStageName.ENTRY: "Visitor",
    FunnelStageName.ZONE_VISIT: "Zone Visit",
    FunnelStageName.BILLING_QUEUE: "Billing Queue",
    FunnelStageName.PURCHASE: "Purchase",
}

BUSINESS_STORY: list[dict[str, str]] = [
    {
        "stage": FunnelStageName.ENTRY.value,
        "label": "Visitor",
        "source": "CCTV pipeline",
        "signal": "Customer session started (store entry / CAM 3 threshold)",
    },
    {
        "stage": FunnelStageName.ZONE_VISIT.value,
        "label": "Zone Visit",
        "source": "CCTV pipeline",
        "signal": "vision.zone.entered — browse, aisle, consultation, promo zones",
    },
    {
        "stage": FunnelStageName.BILLING_QUEUE.value,
        "label": "Billing Queue",
        "source": "CCTV pipeline",
        "signal": "vision.zone.entered — billing_queue, checkout, queue zones",
    },
    {
        "stage": FunnelStageName.PURCHASE.value,
        "label": "Purchase",
        "source": "POS / analytics",
        "signal": "Completed transaction or analytics.purchase.completed event",
    },
]

CONVERSION_FORMULA = (
    "Sequential conversion: for stage S, count visitors who reached both S and the "
    "next stage, divide by visitors who reached S, cap at 100%. "
    "drop_off_rate = 1 − conversion_rate. PURCHASE is terminal (no downstream rate)."
)

END_TO_END_CONVERSION_FORMULA = (
    "Overall purchase conversion (dashboard KPI): min(PURCHASE.count, ENTRY.count) / ENTRY.count, "
    "capped at 100% when POS and CCTV windows differ."
)


def stage_business_label(stage: FunnelStageName | str) -> str:
    if isinstance(stage, str):
        try:
            stage = FunnelStageName(stage)
        except ValueError:
            return stage
    return STAGE_BUSINESS_LABELS.get(stage, stage.value)


def business_story_meta() -> dict[str, object]:
    return {
        "stage_labels": {s.value: STAGE_BUSINESS_LABELS[s] for s in FUNNEL_STAGE_ORDER},
        "business_story": BUSINESS_STORY,
        "conversion_formula": CONVERSION_FORMULA,
        "end_to_end_conversion_formula": END_TO_END_CONVERSION_FORMULA,
        "stage_order": [s.value for s in FUNNEL_STAGE_ORDER],
    }
