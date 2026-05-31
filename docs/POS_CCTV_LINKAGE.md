# POS ↔ CCTV Linkage Evidence

## Business question

How do Brigade Road POS orders connect to in-store shopper journeys captured on CCTV?

## Data sources

| Signal | Source | Field / event |
|--------|--------|----------------|
| **CCTV billing presence** | YOLO pipeline on CAM 5 | `vision.zone.entered` where `zone_type ∈ {billing_queue, checkout, billing, queue}` |
| **POS purchase** | `Brigade_Bangalore_10_April_26.csv` | Completed orders for store **ST1008**, timestamp from `order_date` + `order_time`, revenue from **NMV** |

## Algorithm (`PosIngestionService._correlate_with_cctv`)

1. Collect earliest billing-zone entry per `external_track_id` from CCTV events.
2. Load completed POS transactions for the demo store.
3. Match each transaction to the nearest billing track within **±20 minutes** (`PosLinkMode.AUTO`).
4. Write `session_id` / metadata on linked transactions and emit `analytics.purchase.completed` where configured.

## Dashboard disclosure

The dashboard exposes linkage under `GET /api/v1/stores/{store_id}/dashboard/summary`:

- **POS Purchases (CSV)** — all 24 orders in the CSV (ground-truth retail revenue).
- **Linked Conversion (CCTV↔POS)** — orders matched to a billing-zone track ÷ CCTV entries.
- **`pos_insights.linkage`** — algorithm, window, counts, and plain-language explanation.

## Why counts differ

| Metric | Meaning |
|--------|---------|
| Funnel `PURCHASE` | CCTV journey reached purchase stage (session + billing correlation) |
| POS Purchases | Every completed CSV order |
| Linked purchases | Subset of POS orders with a billing-track time match |

A single shopper may generate multiple zone events; POS records every line-item order. The linkage rate is therefore expected to be **≤ 100%** and is reported explicitly rather than implied.

## Verify locally

```bash
docker compose up --build
curl -H "X-API-Key: purple-demo-key" \
  http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/dashboard/summary
# → pos_insights.linkage.linked_purchases, pos_insights.linkage.explanation
```
