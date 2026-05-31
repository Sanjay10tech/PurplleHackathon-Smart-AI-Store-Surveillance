"""POS analytics schemas for dashboard and API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PosRankItem(BaseModel):
    name: str
    revenue: float
    line_count: int = 0


class PosLinkageEvidence(BaseModel):
    """How POS CSV orders are matched to CCTV billing-zone tracks."""

    algorithm: str = "billing_track_time_window"
    window_minutes: int = 20
    billing_zone_types: list[str] = Field(
        default_factory=lambda: ["billing_queue", "checkout", "billing", "queue"]
    )
    cctv_signal: str = "vision.zone.entered in billing zones (CAM 5)"
    pos_signal: str = "Brigade_Bangalore_10_April_26.csv completed orders (ST1008)"
    linked_purchases: int = 0
    pos_purchases: int = 0
    linkage_rate: float | None = None
    explanation: str = ""


class PosInsights(BaseModel):
    source_file: str = "Brigade_Bangalore_10_April_26.csv"
    revenue_nmv: float = 0.0
    purchase_count: int = 0
    linked_purchases: int = 0
    average_basket_value: float | None = None
    conversion_rate: float | None = None
    top_brands: list[PosRankItem] = Field(default_factory=list)
    top_categories: list[PosRankItem] = Field(default_factory=list)
    column_summary: dict[str, object] = Field(default_factory=dict)
    linkage: PosLinkageEvidence | None = None
