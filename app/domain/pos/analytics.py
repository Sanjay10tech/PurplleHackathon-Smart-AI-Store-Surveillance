"""Aggregate POS order data for dashboard KPIs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.pos.csv_parser import PosOrder


@dataclass(frozen=True)
class RankedItem:
    name: str
    revenue: Decimal
    line_count: int


@dataclass(frozen=True)
class PosAggregates:
    purchase_count: int
    revenue_nmv: Decimal
    average_basket_value: Decimal | None
    top_brands: list[RankedItem]
    top_categories: list[RankedItem]


def aggregate_orders(orders: list[PosOrder], *, top_n: int = 5) -> PosAggregates:
    revenue = sum((o.nmv for o in orders), Decimal("0"))
    count = len(orders)
    aov = (revenue / count) if count > 0 else None

    brand_map: dict[str, tuple[Decimal, int]] = {}
    cat_map: dict[str, tuple[Decimal, int]] = {}
    for order in orders:
        for brand, amount in order.brand_totals.items():
            prev_rev, prev_lines = brand_map.get(brand, (Decimal("0"), 0))
            lines = sum(1 for li in order.line_items if li.brand_name == brand)
            brand_map[brand] = (prev_rev + amount, prev_lines + lines)
        for cat, amount in order.category_totals.items():
            prev_rev, prev_lines = cat_map.get(cat, (Decimal("0"), 0))
            lines = sum(
                1 for li in order.line_items
                if f"{li.dep_name}/{li.sub_category}" == cat
            )
            cat_map[cat] = (prev_rev + amount, prev_lines + lines)

    top_brands = sorted(
        (RankedItem(name=k, revenue=v[0], line_count=v[1]) for k, v in brand_map.items()),
        key=lambda x: x.revenue,
        reverse=True,
    )[:top_n]

    top_categories = sorted(
        (RankedItem(name=k, revenue=v[0], line_count=v[1]) for k, v in cat_map.items()),
        key=lambda x: x.revenue,
        reverse=True,
    )[:top_n]

    return PosAggregates(
        purchase_count=count,
        revenue_nmv=revenue,
        average_basket_value=aov,
        top_brands=top_brands,
        top_categories=top_categories,
    )
