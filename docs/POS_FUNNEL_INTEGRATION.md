# POS + CCTV Funnel Integration Report

**Generated:** 2026-05-30T16:11:47.166912+00:00
**Store:** Brigade_Bangalore (`00000000-0000-0000-0000-000000000101`) · **POS file:** `Brigade_Bangalore_10_April_26.csv`
**Analysis period:** 2026-04-10T00:00:00+00:00 → 2026-05-31T23:59:59+00:00

## 1. CSV column identification

### Transaction columns

Identifiers and line-item fields used to define a **purchase event**:

| Column | Role |
|--------|------|
| `order_id` | Transaction / basket ID (multiple line rows per order) |
| `invoice_number` | POS receipt ID (stored as `transactions.external_ref`) |
| `invoice_type` | `sales` = completed purchase; filtered for ingest |
| `order_date` + `order_time` | **Billing timestamp** (DD-MM-YYYY HH:MM:SS) |
| `store_id` / `store_name` | Store filter (`ST1008` / Brigade_Bangalore) |
| `sku`, `product_id`, `qty` | Line-item product detail |

### Revenue columns

| Column | Meaning | Used |
|--------|---------|:----:|
| `NMV` | Net Merchandise Value (after discounts) | **Yes** — transaction amount |
| `GMV` | Gross Merchandise Value (list price × qty) | Metadata |
| `total_amount` | Line total including tax adjustments | Cross-check |
| `taxable_amt`, `tax_amt` | Tax breakdown | Metadata |
| `coupon_amount`, `item_promotion` | Discount components | Metadata |

**Line rows in CSV:** 101 · **Distinct orders:** 24

### Purchase events

- **Key:** `order_id (line items) → invoice_number (receipt)`
- **Recommended amount field:** `NMV (Net Merchandise Value after discounts)`
- **Billing timestamps:** `order_date, order_time`

## 2. POS summary (real data — 10 April 2026)

| Metric | Value |
|--------|------:|
| Completed orders | **24** |
| Line items | 101 |
| Revenue (NMV) | **₹34,831.74** |
| Revenue (GMV) | ₹44,920.00 |
| First billing | 12:15:05 |
| Last billing | 21:39:55 |

### Billing timestamps (sample orders)

| Time (UTC) | Invoice | NMV (₹) | Customer |
|------------|---------|--------:|----------|
| 2026-04-10 12:15:05 | `ML0426KAP0001321` | 1,247.98 | sugitha |
| 2026-04-10 12:42:18 | `ML0426KAP0001324` | 8,243.23 | thanu thanu |
| 2026-04-10 13:41:55 | `ML0426KAP0001333` | 198.00 | madeeha thaseeb |
| 2026-04-10 13:55:16 | `ML0426KAP0001336` | 199.00 | sera |
| 2026-04-10 14:23:21 | `ML0426KAP0001337` | 225.00 | Bharti  Bajaj |
| 2026-04-10 15:02:20 | `ML0426KAP0001340` | 814.98 | suman |
| 2026-04-10 15:46:39 | `ML0426KAP0001346` | 599.00 | Guest |
| 2026-04-10 15:50:44 | `ML0426KAP0001347` | 400.00 | zthise |
| … | *16 more orders* | | |

### Evening window (CCTV pilot overlap ≥ 20:00)

| Orders | NMV (₹) |
|-------:|--------:|
| 3 | 1,594.59 |

**CCTV footage window (~20:10–20:12):** 1 POS order(s) in 20:10–20:30 band.

## 3. Integrated funnel (Visitors → Billing Queue → Purchase)

Stages combine **CCTV vision events** (visitors, billing queue) with **ingested POS transactions** (purchase).

```
  Visitors (CCTV)     Billing Queue (CCTV)     Purchase (POS)
        22        ───────────────►             5        ───────────────►       24
```

| Stage | Count | Source |
|-------|------:|--------|
| **Visitors** | **22** | CCTV — distinct `external_track_id` (vision pipeline) |
| **Billing Queue** | **5** | CCTV — first-touch `billing_queue` / `checkout` zone enters |
| **Purchase** | **24** | POS — completed `transactions` (NMV, status=completed) |

## 4. Calculated KPIs (real data)

| KPI | Formula | Value |
|-----|---------|------:|
| **Conversion rate** (Billing Queue → Purchase) | min(purchases,billing) / billing_queue | **100.00%** |
| **Purchase rate** (Visitors → Purchase) | min(purchases,visitors) / unique_visitors | **100.00%** |
| **Revenue** | Σ transaction NMV | **₹34,831.74** |
| **Revenue per visitor** | revenue / unique_visitors | **₹1,583.26** |

*Raw ratios (uncapped): billing→purchase 480.00%, visitor→purchase 109.09% — POS covers full store day (24 orders) while CCTV billing-queue counts come from ~12 min pilot footage.*

### Funnel stage detail (API/engine)

| Stage | Count | Re-entries | Conversion | Drop-off |
|-------|------:|-----------:|-----------:|---------:|
| ENTRY | 2 | 3 | 0.0000 | 1.0000 |
| ZONE_VISIT | 14 | 101 | 0.0000 | 1.0000 |
| BILLING_QUEUE | 5 | 10 | 0.0000 | 1.0000 |
| PURCHASE | 24 | 0 | — | — |

## 5. Data alignment notes

- **POS billing timestamps** are real store-local times on **10-Apr-2026** (`order_date` + `order_time`).
- **CCTV vision events** in PostgreSQL use pipeline ingest timestamps (~May 2026 reprocessing of April footage).
- Integrated KPIs use a **wide analysis window** spanning both datasets; stages are sourced from real tables, not mock UI values.
- Track-level join (visitor → receipt) is not available without POS–CCTV correlation IDs; counts are stage-level integration.

## 6. Reproduce

```bash
python scripts/ingest_pos_csv.py --replace
python scripts/analyze_pos_funnel_integration.py
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel"
```

---

*POS orders: 24 · CCTV visitors: 22 · Revenue: ₹34,831.74*
