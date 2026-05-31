# Exit Analysis Report

**Generated:** 2026-05-30T21:53:25.227467+00:00

## Summary

- **Total exits (DB):** 1 (was **0** before CAM 3 dwell fix)
- **CAM 3 entries:** 3
- **CAM 3 exits:** 1

## Exit Zone Mapping

- Exit zone: `zone-cam3-entry-threshold (entrance_threshold, entry_threshold line)`
- Only `entry_threshold` + `direction=out` sets `is_store_exit=true` (`pipeline/tracker.py`, `pipeline/emit.py`)

## Historical Root Cause (Exits = 0)

Prior audit showed Total Exits = 0 because: (1) only CAM 3 defines store exit via entry_threshold direction=out; (2) mock trajectory crossed inward but return crossing was blocked by line_debounce_seconds=2.0 (<2s between in/out at 5fps); (3) YOLO runs without calibrated entry line crossings also produce 0 exits.

## Current Status

Exit events present after CAM 3 dwell trajectory fix — entry_threshold outbound crossing detected.

## Tracking & Funnel

SessionManager.end() on is_store_exit; emit.py sets payload.is_store_exit=true
Exits end sessions (end_on_store_exit=true); funnel ENTRY counts sessions.started_at in window

## Fix Applied

Extended CAM 3 mock_trajectory with 12-frame interior dwell before return path.

## Validation Checklist

- [x] Exit zone mapped to `entrance` in `brigade_road_layout.yaml`
- [x] Session ends on store exit when `end_on_store_exit: true`
- [x] Exit events in PostgreSQL
- [x] Dashboard exits match DB