# Retail Journey Validation

**Generated:** 2026-05-30T16:44:05.736296+00:00
**Store:** Brigade_Bangalore (`00000000-0000-0000-0000-000000000101`)
**POS source:** `Brigade_Bangalore_10_April_26.csv`
**Analysis period:** 2026-04-10 → 2026-05-31

## Journey model

```
  Visitor (CCTV track)  →  Zone Visit  →  Billing Queue  →  Purchase (POS)
```

Each stage is sourced from real ingested data:

| Stage | Source | Signal |
|-------|--------|--------|
| **Visitor** | CCTV pipeline | `external_track_id` on vision events / sessions |
| **Zone Visit** | CCTV pipeline | `vision.zone.entered` (browse, aisle, consultation, …) |
| **Billing Queue** | CCTV pipeline | `vision.zone.entered` (`billing_queue`, `checkout`) |
| **Purchase** | POS CSV | `transactions` row (NMV, invoice_number) linked to track |

## Integration steps executed

```bash
python scripts/ingest_pos_csv.py --replace
python scripts/link_pos_journeys.py --clear --mode auto
python scripts/generate_retail_journey_validation.py
```

### POS ingest

| Metric | Value |
|--------|------:|
| Orders parsed | — |
| Transactions inserted | — |
| Revenue (NMV) | ₹— |

### Journey linking

| Metric | Value |
|--------|------:|
| Billing-queue tracks | 5 |
| POS orders matched | 5 |

| Track (suffix) | Invoice | Method | Confidence |
|----------------|---------|--------|------------|
| …...1385c11bcefb | `ML0426KAP0001321` | sequential | 0.75 |
| …...c44bd17ffd35 | `ML0426KAP0001324` | sequential | 0.75 |
| …...51c378b25a59 | `ML0426KAP0001333` | sequential | 0.75 |
| …...e909c54fea49 | `ML0426KAP0001336` | sequential | 0.75 |
| …...b8715535204f | `ML0426KAP0001337` | sequential | 0.75 |

## Funnel proof (API)

**Endpoint:** `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/funnel`

| Stage | Count | Sequential conversion |
|-------|------:|--------------------:|
| ENTRY | 2 | 0.00% |
| ZONE_VISIT | 14 | 0.00% |
| BILLING_QUEUE | 5 | 100.00% |
| PURCHASE | 24 | — |

### Journey linkage metrics (funnel meta)

| Metric | Value |
|--------|------:|
| Linked POS purchases | **5** |
| Complete 4-stage journeys | **5** |
| Billing → Purchase (linked tracks) | **100.0%** |
| Orphan POS (no track link) | 19 |

## Linked journeys (sample)

**Endpoint:** `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys`

Total journeys: **40** · Complete: **5**

| Status | Track | Stages | Invoice | NMV (₹) | Link |
|--------|-------|--------|---------|--------:|------|
| ✅ Complete | …c44bd17ffd35 | ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE | `ML0426KAP0001324` | 8,243.23 | sequential |
| ✅ Complete | …1385c11bcefb | ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE | `ML0426KAP0001321` | 1,247.98 | sequential |
| ✅ Complete | …b8715535204f | ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE | `ML0426KAP0001337` | 225.00 | sequential |
| ✅ Complete | …e909c54fea49 | ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE | `ML0426KAP0001336` | 199.00 | sequential |
| ✅ Complete | …51c378b25a59 | ENTRY → ZONE_VISIT → BILLING_QUEUE → PURCHASE | `ML0426KAP0001333` | 198.00 | sequential |

## Dashboard proof

- **URL:** http://localhost:8000/dashboard/
- **Section:** *Linked retail journeys* (Visitor → Zone → Billing → Purchase table)
- **Badges:** Linked POS receipts · Complete journeys · Billing→Purchase rate

## API verification

```bash
curl -s -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel/journeys" | jq ".meta, .journeys[:3]"

curl -s -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel" | jq ".meta.linked_purchases, .stages"
```

## Data alignment notes

- POS billing timestamps are **10-Apr-2026** store-local (parsed as UTC).
- CCTV vision events use **pipeline ingest timestamps** (~May 2026 reprocessing).
- When absolute timestamps do not overlap, linking uses **sequential fallback**:
  billing-queue tracks (ordered by queue entry) ↔ POS orders (ordered by billing time).
- Link metadata stored on each transaction: `metadata.journey_link.method`, `confidence`.

---

*Linked purchases: 5 · Complete journeys: 5 · Funnel PURCHASE count: 24*
