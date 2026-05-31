"""
Brigade_Bangalore POS CSV parser — real Purplle store export (ST1008).

Column groups (Brigade_Bangalore_10_April_26.csv):
  Transactions: order_id, invoice_number, invoice_type, store_id, sku, qty
  Revenue: GMV, NMV, total_amount, coupon_amount, item_promotion, taxable_amt
  Product: brand_name, dep_name, sub_category, brand_type, product_name
  Timestamps: order_date (DD-MM-YYYY), order_time (HH:MM:SS)
  Staff: salesperson_name, employee_code
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class PosColumnAnalysis:
    all_columns: tuple[str, ...]
    transaction_columns: tuple[str, ...]
    revenue_columns: tuple[str, ...]
    product_columns: tuple[str, ...]
    timestamp_columns: tuple[str, ...]
    brand_column: str
    category_columns: tuple[str, ...]
    line_count: int
    order_count: int


@dataclass
class PosLineItem:
    sku: str
    product_name: str
    brand_name: str
    dep_name: str
    sub_category: str
    brand_type: str
    qty: int
    gmv: Decimal
    nmv: Decimal
    salesperson_name: str | None


@dataclass
class PosOrder:
    order_id: str
    invoice_number: str
    occurred_at: datetime
    customer_name: str
    customer_number: str | None
    nmv: Decimal
    gmv: Decimal
    total_amount: Decimal
    line_count: int
    line_items: list[PosLineItem] = field(default_factory=list)
    brand_totals: dict[str, Decimal] = field(default_factory=dict)
    category_totals: dict[str, Decimal] = field(default_factory=dict)
    offer_name: str | None = None
    salesperson: str | None = None


def _parse_datetime(order_date: str, order_time: str) -> datetime:
    day, month, year = order_date.split("-")
    hour, minute, second = order_time.split(":")
    return datetime(
        int(year), int(month), int(day),
        int(hour), int(minute), int(second),
        tzinfo=UTC,
    )


def _dec(value: str | None) -> Decimal:
    if not value or not str(value).strip():
        return Decimal("0")
    return Decimal(str(value))


def analyze_columns(rows: list[dict[str, str]]) -> PosColumnAnalysis:
    sample = rows[0] if rows else {}
    cols = tuple(sample.keys())
    orders = {r["order_id"] for r in rows if r.get("order_id")}
    return PosColumnAnalysis(
        all_columns=cols,
        transaction_columns=(
            "order_id", "invoice_number", "invoice_type", "return_id",
            "store_id", "store_name", "sku", "product_id", "qty",
        ),
        revenue_columns=(
            "GMV", "NMV", "total_amount", "coupon_amount", "item_promotion",
            "amt_without_gwp", "taxable_amt", "tax_amt", "pb_eb_sale",
        ),
        product_columns=(
            "product_name", "brand_name", "dep_name", "sub_category", "brand_type",
        ),
        timestamp_columns=("order_date", "order_time"),
        brand_column="brand_name",
        category_columns=("dep_name", "sub_category"),
        line_count=len(rows),
        order_count=len(orders),
    )


def parse_pos_csv(
    csv_path: Path,
    *,
    store_code: str = "ST1008",
) -> tuple[list[PosOrder], PosColumnAnalysis]:
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    analysis = analyze_columns(rows)

    by_order: dict[str, PosOrder] = {}
    for row in rows:
        if row.get("store_id") != store_code:
            continue
        if row.get("invoice_type", "").lower() != "sales":
            continue

        oid = row["order_id"]
        if oid not in by_order:
            by_order[oid] = PosOrder(
                order_id=oid,
                invoice_number=row["invoice_number"],
                occurred_at=_parse_datetime(row["order_date"], row["order_time"]),
                customer_name=(row.get("customer_name") or "").strip(),
                customer_number=row.get("customer_number"),
                nmv=Decimal("0"),
                gmv=Decimal("0"),
                total_amount=Decimal("0"),
                line_count=0,
                offer_name=row.get("offer_name") or None,
                salesperson=row.get("salesperson_name") or None,
            )

        order = by_order[oid]
        nmv = _dec(row.get("NMV"))
        gmv = _dec(row.get("GMV"))
        total = _dec(row.get("total_amount"))
        qty = int(float(row.get("qty") or "0"))

        order.nmv += nmv
        order.gmv += gmv
        order.total_amount += total
        order.line_count += 1

        brand = (row.get("brand_name") or "Unknown").strip()
        dep = (row.get("dep_name") or "unknown").strip()
        sub = (row.get("sub_category") or "unknown").strip()
        category_key = f"{dep}/{sub}"

        order.brand_totals[brand] = order.brand_totals.get(brand, Decimal("0")) + nmv
        order.category_totals[category_key] = (
            order.category_totals.get(category_key, Decimal("0")) + nmv
        )

        order.line_items.append(
            PosLineItem(
                sku=row.get("sku") or "",
                product_name=row.get("product_name") or "",
                brand_name=brand,
                dep_name=dep,
                sub_category=sub,
                brand_type=row.get("brand_type") or "",
                qty=qty,
                gmv=gmv,
                nmv=nmv,
                salesperson_name=row.get("salesperson_name"),
            )
        )

    orders = sorted(by_order.values(), key=lambda o: o.occurred_at)
    return orders, analysis
