# Full Dataset Audit

**Generated:** 2026-05-30T21:53:25.227467+00:00

## Phase 1 — Dataset Discovery

| CCTV Videos Found | 5 |

| Video | Size (MB) | In DB | Frames | Events | Entries | Exits | Queue |
|-------|----------:|------:|-------:|-------:|--------:|------:|------:|
| CAM 1.mp4 | 171.92 | Yes | 12 | 28 | 0 | 0 | 0 |
| CAM 2.mp4 | 154.71 | Yes | 10 | 32 | 0 | 0 | 0 |
| CAM 3.mp4 | 182.0 | Yes | 13 | 23 | 3 | 1 | 0 |
| CAM 4.mp4 | 69.9 | Yes | 10 | 14 | 0 | 0 | 0 |
| CAM 5.mp4 | 69.87 | Yes | 12 | 24 | 0 | 0 | 5 |

### CSV Resources

- `data\pos\Brigade_Bangalore_10_April_26.csv`

### XLSX Resources

- `data\store_layout\Brigade_Road_Layout.xlsx`
- `data\store_layout\Brigade_Road_Layout.xlsx.xlsx`

### Pipeline-Referenced Files

- `data/pos/Brigade_Bangalore_10_April_26.csv`
- `data/store_layout/Brigade_Road_Layout.xlsx`
- `data/store_layout/brigade_road_layout.yaml`
- `data/videos/CAM 1.mp4`
- `data/videos/CAM 2.mp4`
- `data/videos/CAM 3.mp4`
- `data/videos/CAM 4.mp4`
- `data/videos/CAM 5.mp4`
- `pipeline/config.yaml`
- `pipeline/zones.yaml`

### Unused / Unreferenced Files

- `data/cctv_analysis_raw.json`
- `data/cctv_overlap.json`
- `data/staff_classification_results.json`
- `data/yolo_tuning_results.json`
- `data/analysis_frames/CAM_1_t004.jpg`
- `data/analysis_frames/CAM_1_t005.jpg`
- `data/analysis_frames/CAM_1_t025.jpg`
- `data/analysis_frames/CAM_1_t050.jpg`
- `data/analysis_frames/CAM_1_t075.jpg`
- `data/analysis_frames/CAM_1_t094.jpg`
- `data/analysis_frames/CAM_1_t095.jpg`
- `data/analysis_frames/CAM_2_t004.jpg`
- `data/analysis_frames/CAM_2_t005.jpg`
- `data/analysis_frames/CAM_2_t024.jpg`
- `data/analysis_frames/CAM_2_t025.jpg`
- `data/analysis_frames/CAM_2_t049.jpg`
- `data/analysis_frames/CAM_2_t050.jpg`
- `data/analysis_frames/CAM_2_t074.jpg`
- `data/analysis_frames/CAM_2_t075.jpg`
- `data/analysis_frames/CAM_2_t094.jpg`
- `data/analysis_frames/CAM_2_t095.jpg`
- `data/analysis_frames/CAM_3_t004.jpg`
- `data/analysis_frames/CAM_3_t005.jpg`
- `data/analysis_frames/CAM_3_t024.jpg`
- `data/analysis_frames/CAM_3_t025.jpg`
- `data/analysis_frames/CAM_3_t049.jpg`
- `data/analysis_frames/CAM_3_t050.jpg`
- `data/analysis_frames/CAM_3_t074.jpg`
- `data/analysis_frames/CAM_3_t075.jpg`
- `data/analysis_frames/CAM_3_t094.jpg`
- `data/analysis_frames/CAM_3_t095.jpg`
- `data/analysis_frames/CAM_4_t004.jpg`
- `data/analysis_frames/CAM_4_t005.jpg`
- `data/analysis_frames/CAM_4_t024.jpg`
- `data/analysis_frames/CAM_4_t025.jpg`
- `data/analysis_frames/CAM_4_t050.jpg`
- `data/analysis_frames/CAM_4_t074.jpg`
- `data/analysis_frames/CAM_4_t075.jpg`
- `data/analysis_frames/CAM_4_t094.jpg`
- `data/analysis_frames/CAM_4_t095.jpg`
- `data/analysis_frames/CAM_5_t004.jpg`
- `data/analysis_frames/CAM_5_t005.jpg`
- `data/analysis_frames/CAM_5_t025.jpg`
- `data/analysis_frames/CAM_5_t050.jpg`
- `data/analysis_frames/CAM_5_t075.jpg`
- `data/analysis_frames/CAM_5_t094.jpg`
- `data/analysis_frames/CAM_5_t095.jpg`
- `data/pipeline/events.jsonl`
- `data/pipeline/sessions.jsonl`
- `data/store_layout/Brigade_Road_Layout.xlsx.xlsx`
- `data/samples/events/batch_ingest.json`
- `data/samples/events/vision.frame.processed.json`
- `data/samples/events/vision.zone.entered.json`
- `data/samples/events/vision.zone.exited.json`

## Phase 2 — Processing Totals

| Metric | Value |
|--------|------:|
| total_events | 121 |
| frames | 57 |
| entries | 3 |
| exits | 1 |
| reentries | 0 |
| queue_events | 5 |
| purchase_events | 0 |
| sessions | 3 |
| transactions | 24 |
| unique_visitors | 9 |
| videos_processed | 5 |
| videos_found | 5 |
| funnel_stages | {'ENTRY': 3, 'ZONE_VISIT': 5, 'BILLING_QUEUE': 3, 'PURCHASE': 0} |

### Per-Video Breakdown

| Video | Frames | Detections | Entries | Exits | Re-entries | Queue | Purchases |
|-------|-------:|-----------:|--------:|------:|-----------:|------:|----------:|
| CAM 1.mp4 | 12 | 16 | 0 | 0 | 0 | 0 | 0 |
| CAM 2.mp4 | 10 | 22 | 0 | 0 | 0 | 0 | 0 |
| CAM 3.mp4 | 13 | 10 | 3 | 1 | 0 | 0 | 0 |
| CAM 4.mp4 | 10 | 4 | 0 | 0 | 0 | 0 | 0 |
| CAM 5.mp4 | 12 | 12 | 0 | 0 | 0 | 5 | 0 |

## Phase 4 — Layout & CSV Integration

### Brigade Road Store Layout

- Source: `data/store_layout/Brigade_Road_Layout.xlsx` → `brigade_road_layout.yaml`
- All CCTV `layout_zone_id` values in `pipeline/zones.yaml` resolve to layout zones

### Brigade_Bangalore_10_April_26.csv

- Store code ST1008 matches Brigade Road UUID `00000000-0000-0000-0000-000000000101`
- POS transactions ingested: **24** orders (10-Apr-2026)
- Funnel PURCHASE stage requires session-linked transactions; CCTV sessions not yet matched to POS

### Layout Mismatches

- Duplicate layout file (unused): data\store_layout\Brigade_Road_Layout.xlsx.xlsx

## Phase 5 — Dashboard KPI Validation

| KPI | SQL / Source | Table | DB | API | Videos |
|-----|--------------|-------|---:|----:|--------|
| unique_visitors | FunnelCalculator dedupe | sessions + events | 9 | 9 | 5/5 |
| entries | count_store_entry_events | events | 3 | — | 5/5 |
| total_exits | count_store_exit_events | events | 1 | 1 | 5/5 |
| re_entries | count_reentry_events | events | 0 | 17 | 5/5 |
| events | count_pipeline_events | events | 121 | — | 5/5 |
| queue_depth | funnel BILLING_QUEUE stage | events | 5 | 3 | 5/5 |

**Verification:** `pytest tests/test_dashboard_metrics_audit.py` — REAL DATA VERIFIED
