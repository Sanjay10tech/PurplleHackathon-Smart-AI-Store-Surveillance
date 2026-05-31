"""Rank uncovered regions by combined line + branch impact."""
from __future__ import annotations

import json
from pathlib import Path

DESCRIPTIONS: dict[str, dict[int | str, str]] = {
    "app/repositories/store_metric_repository.py": {
        61: "SQLite upsert: IntegrityError -> re-fetch bucket and update",
        "98->100": "get_by_store: skip granularity filter when None",
        "100->102": "get_by_store: skip from_ts filter when None",
        "102->104": "get_by_store: skip to_ts filter when None",
    },
    "app/repositories/transaction_repository.py": {
        29: "create_idempotent: IntegrityError recovery via external_ref",
        "62->64": "list_by_store: skip from_ts filter when None",
        "64->66": "list_by_store: skip to_ts filter when None",
    },
    "app/repositories/event_repository.py": {
        37: "create_idempotent: IntegrityError -> idempotency_key lookup",
        "71->73": "list_by_store: skip event_types filter when None",
        "91->93": "count_by_store_and_type: skip from_ts when None",
        "93->95": "count_by_store_and_type: skip to_ts when None",
    },
    "app/services/funnel_service.py": {
        "134->127": "Purchase loop: signal is None -> skip append",
        208: "_resolve_visitor_key: cache miss -> compute and store key",
        239: "_event_to_signal: PURCHASE event type fallback stage",
        258: "_purchase_to_signal: tx.session_id is None -> return None",
        266: "_purchase_to_signal: orphan session -> return None",
        290: "_resolve_stage_from_payload: no funnel_stage/zone_type -> None",
    },
    "app/routers/health.py": {24: "GET /health: assign response.status_code from service"},
    "app/routers/events.py": {
        77: "Batch ingest: JSONResponse 202/207/422 wrapper",
        89: "Single ingest: JSONResponse 202 wrapper",
        "101->100": "ValidationError: batch-too-large detail branch",
    },
    "app/services/heatmap_service.py": {
        122: "_build_visits: zone_key is None -> skip event",
        "132->117": "_build_visits: zone exit without dwell -> skip",
        163: "_extract_dwell_seconds: dwell_seconds key path",
    },
    "app/services/anomaly_service.py": {165: "_zone_summaries: skip non zone.entered events"},
    "app/services/event_ingestion_service.py": {
        45: "ingest(): raise ValidationError on rejected single event",
        "59->62": "ingest_batch(): validator reset_cache guard",
        "140->150": "_process_one(): duplicate by pre-fetched existing_ids",
    },
    "app/services/health_service.py": {32: "_as_utc(): tz-aware datetime path (not naive)"},
    "app/database.py": {
        67: "get_db_session(): commit after successful yield",
        "89->91": "dispose_engine(): skip dispose when _engine is None",
    },
    "app/domain/anomaly/detector.py": {
        212: "_detect_conversion_drop: drop below WARN threshold -> return []",
        "205->206": "_detect_conversion_drop: WARN vs CRITICAL severity branch",
    },
}

data = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
totals = data["totals"]
denom = totals["num_statements"] + totals["num_branches"]
pct = totals["percent_covered"]

regions: list[tuple[str, str, str, int, float]] = []

for fpath, fdata in data["files"].items():
    norm = fpath.replace("\\", "/")
    if "app/" in norm:
        rel = "app/" + norm.split("app/", 1)[1]
    else:
        continue

    missing = sorted(fdata.get("missing_lines") or [])
    if missing:
        # group consecutive lines
        start = prev = missing[0]
        group = [start]
        for ln in missing[1:]:
            if ln == prev + 1:
                group.append(ln)
            else:
                label = f"L{group[0]}" if len(group) == 1 else f"L{group[0]}-{group[-1]}"
                desc = DESCRIPTIONS.get(rel, {}).get(group[0], "uncovered statements")
                regions.append((rel, label, desc, len(group), len(group) / denom * 100))
                group = [ln]
            prev = ln
        label = f"L{group[0]}" if len(group) == 1 else f"L{group[0]}-{group[-1]}"
        desc = DESCRIPTIONS.get(rel, {}).get(group[0], "uncovered statements")
        regions.append((rel, label, desc, len(group), len(group) / denom * 100))

    for br in fdata.get("missing_branches") or []:
        if len(br) >= 2:
            start, end = br[0], br[1]
            br_key = f"L{start}->{end}"
            key = br_key
            desc = DESCRIPTIONS.get(rel, {}).get(key, f"partial branch {start}->{end}")
            regions.append((rel, br_key, desc, 1, 1 / denom * 100))

regions.sort(key=lambda x: (-x[3], -x[4], x[0]))

print("=== COVERAGE SUMMARY ===")
print(f"Current:  {pct:.2f}%  |  Gap to 100%: {100 - pct:.2f}%")
print(f"Baseline gap (87.92% -> 100%): 12.08%  |  Closed: {pct - 87.92:.2f}%  |  Remaining: {100 - pct:.2f}%")
print(f"Uncovered: {totals['missing_lines']} lines + {totals['missing_branches']} branch arms = {totals['missing_lines'] + totals['missing_branches']} elements")
print()
print("=== TOP 20 UNCOVERED REGIONS (by element count -> coverage impact) ===")
print(f"{'#':>3}  {'Wt':>3}  {'Impact':>7}  {'File':<45}  Description")
print("-" * 110)
cumulative = 0.0
for i, (rel, label, desc, wt, imp) in enumerate(regions[:20], 1):
    cumulative += imp
    short = rel.replace("app/", "")
    print(f"{i:3}.  {wt:3}  {imp:6.3f}%  {short:<45}  [{label}] {desc}")

print(f"\nTop 20 cumulative impact: {cumulative:.2f}% of total measurable elements")
print(f"(Closing all 71 remaining elements would reach ~100%; current gap is {100 - pct:.2f}%)")
