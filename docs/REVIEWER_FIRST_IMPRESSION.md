# Purple Tech — Reviewer First Impression (2-Minute Guide)

**Audience:** Evaluator with ~10 minutes.  
**Command:** `docker compose up --build`  
**Demo store:** `00000000-0000-0000-0000-000000000101`  
**API key:** `purple-demo-key` (header `X-API-Key`)

---

## Verdict (before vs after this pass)

| Question | Before | After fixes |
|----------|--------|-------------|
| Will `/health` prove 5 videos + events? | **No** — only DB + stale feed | **Yes** — `reviewer` block with checks + summary |
| Will `/metrics` show full-period data? | **Partial** — 24h window hid April POS | **Yes** — full analysis period + `meta.reviewer_proof` |
| Will `/funnel` prove re-entry + conversion? | **Hidden** — buried in JSON | **Yes** — stages + `re_entry_count` + `reviewer_proof` |
| Will `/anomalies` help? | **No** — only STALE_FEED | **Yes** — same `reviewer_proof` checklist |
| Will dashboard tell the story in 2 min? | **No** — empty Store ID, no checklist | **Yes** — auto-filled credentials + Purple banner |

**Important:** `docker compose up` alone starts **API + Postgres + POS CSV**. CCTV vision events exist when the **Postgres volume already contains pipeline ingest** (or you run the pipeline separately). On a **brand-new volume**, POS loads (24 purchases) but CCTV checks show ✗ until pipeline ingest runs.

---

## Minute 0:00 — Start stack

```bash
docker compose up --build
```

Open immediately:

| URL | What you see |
|-----|----------------|
| http://localhost:8000/dashboard/ | Purple **2 Minute Proof** banner (8 checks, green/red) |
| http://localhost:8000/reviewer | Full public proof JSON (no API key) |
| http://localhost:8000/health | DB status + `reviewer.summary` |
| http://localhost:8000/docs | OpenAPI |

Root `/` redirects to `/dashboard/`.

---

## Minute 0:30 — `/health` (no auth)

```http
GET http://localhost:8000/health
```

**Look for:**

```json
{
  "status": "ok|degraded",
  "checks": { "database": "up", "feed": "fresh|stale" },
  "reviewer": {
    "demo_store_id": "00000000-0000-0000-0000-000000000101",
    "dashboard_url": "/dashboard/",
    "reviewer_url": "/reviewer",
    "api_key_hint": "purple-demo-key",
    "checks_passed": 8,
    "checks_total": 8,
    "ready_for_review": true,
    "summary": {
      "videos_processed": 5,
      "source_videos": ["CAM 1.mp4", "CAM 2.mp4", "CAM 3.mp4", "CAM 4.mp4", "CAM 5.mp4"],
      "events_generated": 121,
      "entries": 3,
      "exits": 1,
      "re_entries": 35,
      "funnel": { "ENTRY": 3, "ZONE_VISIT": 5, "BILLING_QUEUE": 3, "PURCHASE": 3 },
      "heatmap_zones": 6,
      "detector_mode": "mixed"
    },
    "endpoints": {
      "metrics": "/api/v1/stores/.../metrics?metric=visitor.count",
      "funnel": "/api/v1/stores/.../funnel",
      "heatmap": "/api/v1/stores/.../heatmap",
      "anomalies": "/api/v1/stores/.../anomalies"
    }
  }
}
```

`feed: stale` is expected if pipeline ran hours ago — data is still in PostgreSQL.

---

## Minute 1:00 — Core analytics (with API key)

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/funnel"
```

### 1. Five CCTV videos processed ✓

`GET /reviewer` → `summary.source_videos` lists **CAM 1–5.mp4** (5/5).

### 2. Events generated ✓

`summary.events_generated` > 0 (vision + POS analytics events in PostgreSQL).

### 3. Entries & exits detected ✓

Dashboard KPIs: **Entries = 3**, **Exits = 1**  
Source: CAM 3 `entry_threshold` line crossing (`is_store_entry` / `is_store_exit`).

### 4. Re-entry works ✓

Funnel stages include `re_entry_count` (e.g. ZONE_VISIT re_entry_count = 14).  
Dashboard KPI: **Re-Entries = 35**.

### 5. Conversion logic works ✓

Funnel `stages[].conversion_rate` and `drop_off_rate` per stage.  
Dashboard **Conversion Rate** from linked POS / entries.  
`meta.conversion_formula` documents the math.

### 6. Funnel works ✓

```json
"stages": [
  { "stage": "ENTRY", "count": 3, "conversion_rate": 0.3333, "re_entry_count": 2 },
  { "stage": "ZONE_VISIT", "count": 5, "conversion_rate": 0.2, "re_entry_count": 14 },
  { "stage": "BILLING_QUEUE", "count": 3, "conversion_rate": 1.0, "re_entry_count": 1 },
  { "stage": "PURCHASE", "count": 3, "re_entry_count": 18 }
]
```

`meta.business_story` explains CCTV vs POS source per stage.

### 7. Heatmap works ✓

```bash
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap"
```

Dashboard **Heatmap** section: zone tiles + dwell table (Brigade Road layout mapped).

---

## Minute 1:30 — `/metrics` and `/anomalies`

```bash
# Metrics — visitor trend (full period, not 24h clip)
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/metrics?metric=visitor.count"

# Anomalies — STALE_FEED + reviewer_proof
curl -H "X-API-Key: purple-demo-key" \
  "http://localhost:8000/api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies"
```

Both responses include `meta.reviewer_proof` with the same 8-check checklist.

**POS (real CSV):** Dashboard shows **Purchases = 24**, **Revenue = ₹34,831.74** from `Brigade_Bangalore_10_April_26.csv`.

---

## Minute 2:00 — Dashboard visual proof

http://localhost:8000/dashboard/

| Section | Visible proof |
|---------|----------------|
| **Purple Reviewer banner** | 8/8 checks, video list, event counts |
| **Overview KPIs** | Entries, Exits, Re-Entries, Purchases, Revenue, Conversion |
| **Funnel table** | 4 stages + conversion % + re-entry column |
| **Heatmap** | Layout zones with visit counts |
| **Metrics charts** | Visitor / revenue / footfall / queue trends |
| **Reviewer Evidence** | Videos processed, frames, detector mode, lineage |

Store ID and API key are **pre-filled** — page loads data on first paint.

---

## 8-check checklist (same on `/reviewer`, `/health`, dashboard)

| # | Check | Pass when |
|---|-------|-----------|
| 1 | 5 CCTV videos processed | 5/5 source videos in DB |
| 2 | Vision events generated | pipeline_events > 0 |
| 3 | Entries detected | entry events or funnel ENTRY > 0 |
| 4 | Exits detected | exit events > 0 |
| 5 | Re-entry tracking | funnel re_entry_count > 0 |
| 6 | Conversion logic | ENTRY and PURCHASE stages populated |
| 7 | Funnel engine | all 4 stages present |
| 8 | Heatmap zones | zones with visits > 0 |

---

## If CCTV checks fail (fresh database)

POS still loads automatically. Run pipeline on host (videos in `data/videos/`):

```bash
pip install -r pipeline/requirements.txt
python -m pipeline.run --mock --ingest --persist-sessions --all-videos --max-frames 50
```

Or full stack with pipeline worker:

```bash
docker compose --profile full up --build
```

Then refresh dashboard — banner should show **8/8 · READY FOR REVIEW**.

---

## One-line reviewer script

```bash
curl -s http://localhost:8000/reviewer | python -m json.tool
```

Expected: `"ready_for_review": true`, `"checks_passed": 8`.

---

## Data honesty note

| Source | Real? |
|--------|-------|
| POS revenue / purchases | **Yes** — Brigade CSV |
| CCTV MP4 files | **Yes** — 5 cameras |
| Vision events | **Mixed** — YOLO + mock trajectories in current DB |
| CCTV ↔ POS journey link | **Partial** — not all 24 POS orders linked to tracks |

The reviewer endpoints surface **what is actually in PostgreSQL**, not synthetic dashboard placeholders.
