#!/usr/bin/env python3
"""Parse Brigade_Road_Layout.xlsx and generate layout validation report."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.domain.heatmap.layout_mapping import load_store_layout  # noqa: E402

DEMO_STORE_ID = "00000000-0000-0000-0000-000000000101"
LAYOUT_XLSX = REPO_ROOT / "data" / "store_layout" / "Brigade_Road_Layout.xlsx"
PIPELINE_ZONES = REPO_ROOT / "pipeline" / "zones.yaml"
LAYOUT_YAML = REPO_ROOT / "app" / "domain" / "heatmap" / "brigade_road_layout.yaml"
EVIDENCE_PNG = REPO_ROOT / "docs" / "evidence" / "brigade_road_layout.png"


@dataclass
class ExcelLabel:
    text: str
    plan_x: float
    plan_y: float
    revision: str = "current"


@dataclass
class CameraZoneRow:
    camera_id: str
    camera_name: str
    zone_id: str
    generic_name: str
    store_name: str
    zone_type: str
    layout_zone_id: str | None
    layout_label: str | None
    points: list
    in_db: bool = False


def _parse_excel_drawing(xlsx: Path) -> tuple[list[ExcelLabel], dict]:
    """Extract floor-plan PNG and label anchors from embedded drawing."""
    with zipfile.ZipFile(xlsx) as z:
        EVIDENCE_PNG.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PNG.write_bytes(z.read("xl/media/image1.png"))
        drawing = z.read("xl/drawings/drawing1.xml").decode("utf-8")

    pic = re.search(
        r"<xdr:pic>.*?<a:off x=\"(\d+)\" y=\"(\d+)\"/>.*?<a:ext cx=\"(\d+)\" cy=\"(\d+)\"",
        drawing,
        re.S,
    )
    if not pic:
        return [], {"image_extracted": str(EVIDENCE_PNG)}

    ix, iy, icx, icy = map(int, pic.groups())
    meta = {
        "image_extracted": str(EVIDENCE_PNG.relative_to(REPO_ROOT)),
        "image_anchor_emu": {"x": ix, "y": iy, "w": icx, "h": icy},
    }

    blocks = re.findall(
        r'<xdr:sp macro="" textlink="">.*?<a:off x="(\d+)" y="(\d+)"/>.*?'
        r'<a:ext cx="(\d+)" cy="(\d+)".*?<a:t>([^<]*)</a:t>',
        drawing,
        re.S,
    )

    labels: list[ExcelLabel] = []
    seen: set[str] = set()
    for x, y, _cx, _cy, text in blocks:
        t = text.replace("&amp;", "&").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        px = round((int(x) - ix) / icx, 4)
        py = round((int(y) - iy) / icy, 4)
        revision = "revised" if px < 0.45 else "current"
        labels.append(ExcelLabel(text=t, plan_x=px, plan_y=py, revision=revision))

    return labels, meta


def _load_pipeline_zones() -> dict[str, list[dict]]:
    raw = yaml.safe_load(PIPELINE_ZONES.read_text(encoding="utf-8"))
    return raw.get("zones", {})


CAMERA_NAMES = {
    "00000000-0000-0000-0000-000000000201": "CAM 1",
    "00000000-0000-0000-0000-000000000202": "CAM 2",
    "00000000-0000-0000-0000-000000000203": "CAM 3",
    "00000000-0000-0000-0000-000000000204": "CAM 4",
    "00000000-0000-0000-0000-000000000205": "CAM 5",
}

# Generic pipeline name → Brigade Road layout zone id
GENERIC_TO_LAYOUT: dict[str, str] = {
    "aisle_circulation": "foh_circulation",
    "browse_skincare_wall": "skincare_wall",
    "browse_cosmetics_wall": "cosmetics_wall",
    "promo_beat_the_heat": "promo_island_central",
    "promo_summer_essentials": "promo_island_south",
    "consultation_desk": "consultation_skincare",
    "consultation_makeup": "consultation_makeup",
    "entry_threshold": "entrance",
    "entry_landing": "entrance",
    "billing_queue": "billing_queue",
    "checkout_active": "cash_counter",
    "checkout_staff": "cash_counter",
    "stock_floor": "stockroom",
    "door_to_sales": "stockroom",
    "occlusion_mask": "entrance",
    "aisle_entry_line": "foh_circulation",
    "aisle_left_mouth": "foh_circulation",
    "queue_entry_line": "billing_queue",
}

STORE_ZONE_NAMES: dict[str, str] = {
    "foh_circulation": "Front of House (F.O.H.)",
    "skincare_wall": "Skincare Brand Wall",
    "cosmetics_wall": "Cosmetics Brand Wall",
    "promo_island_central": "Promo Island — Beat the Heat",
    "promo_island_south": "Promo Island — Summer Essentials",
    "consultation_skincare": "Skincare Consultation Desk",
    "consultation_makeup": "Makeup Consultation Station",
    "entrance": "Store Entrance",
    "billing_queue": "Billing Queue",
    "cash_counter": "Cash Counter",
    "stockroom": "Stockroom",
}


def _build_camera_rows(layout, db_zone_ids: set[str]) -> list[CameraZoneRow]:
    pipeline = _load_pipeline_zones()
    rows: list[CameraZoneRow] = []
    for cam_id, zones in pipeline.items():
        cam_name = CAMERA_NAMES.get(cam_id, cam_id)
        for z in zones:
            zone_id = z["zone_id"]
            generic = z.get("name", zone_id)
            layout_id = (
                z.get("layout_zone_id")
                or layout.camera_zone_mapping.get(zone_id)
                or GENERIC_TO_LAYOUT.get(generic)
            )
            layout_zone = layout.zones_by_id.get(layout_id) if layout_id else None
            store_name = layout_zone.label if layout_zone else STORE_ZONE_NAMES.get(layout_id or "", generic)
            rows.append(
                CameraZoneRow(
                    camera_id=cam_id,
                    camera_name=cam_name,
                    zone_id=zone_id,
                    generic_name=generic,
                    store_name=store_name,
                    zone_type=z.get("zone_type", ""),
                    layout_zone_id=layout_id,
                    layout_label=layout_zone.label if layout_zone else None,
                    points=z.get("points", []),
                    in_db=zone_id in db_zone_ids,
                )
            )
    return rows


async def _fetch_db_zone_ids() -> set[str]:
    from sqlalchemy import text

    from app.database import create_engine, create_session_factory, dispose_engine, reset_engine_singleton

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = url
    reset_engine_singleton()
    engine = create_engine()
    sf = create_session_factory(engine)
    async with sf() as session:
        result = await session.execute(
            text(
                """
                SELECT DISTINCT payload->>'zone_id' AS zone_id
                FROM events
                WHERE store_id = :store
                  AND event_type IN ('vision.zone.entered', 'vision.zone.exited')
                  AND payload->>'zone_id' IS NOT NULL
                """
            ),
            {"store": DEMO_STORE_ID},
        )
        ids = {r.zone_id for r in result if r.zone_id}
    await dispose_engine()
    return ids


def _fetch_heatmap() -> dict:
    base = os.environ.get("API_BASE", "http://localhost:8000")
    key = os.environ.get("API_KEY", "purple-demo-key")
    req = urllib.request.Request(
        f"{base}/api/v1/stores/{DEMO_STORE_ID}/heatmap",
        headers={"X-API-Key": key},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _format_points(points: list) -> str:
    if not points:
        return "—"
    if len(points) == 2 and all(len(p) == 2 for p in points):
        return f"line {points[0]} → {points[1]}"
    return "; ".join(str(p) for p in points[:4]) + ("…" if len(points) > 4 else "")


def _write_report(
    layout,
    excel_labels: list[ExcelLabel],
    excel_meta: dict,
    camera_rows: list[CameraZoneRow],
    heatmap: dict,
    db_zone_ids: set[str],
) -> Path:
    heatmap_zones = heatmap.get("zones", [])
    layout_mapped = heatmap.get("meta", {}).get("layout_mapped", False)
    mapped_camera = set(layout.camera_zone_mapping)
    unmapped_db = sorted(db_zone_ids - mapped_camera)
    layout_without_camera = sorted(layout.layout_zone_ids - set(layout.camera_zone_mapping.values()))
    missing_mappings = [
        r for r in camera_rows if r.layout_zone_id is None and r.zone_type not in ("ignore",)
    ]

    lines = [
        "# Brigade Road Layout Validation Report",
        "",
        f"**Generated:** {datetime.now(tz=UTC).isoformat()}",
        f"**Store:** {layout.store_name} (`{layout.store_id}`) · **Code:** {layout.store_code}",
        f"**Excel source:** `{layout.source_file}` (revision labels: Revised / Current)",
        f"**Floor plan image:** `{excel_meta.get('image_extracted', '—')}`",
        "",
        "## Executive summary",
        "",
        "| Check | Status |",
        "|-------|--------|",
        f"| Excel floor plan parsed | {'PASS' if excel_labels else 'WARN'} | {len(excel_labels)} brand/zone labels extracted |",
        f"| Layout YAML loaded | PASS | {len(layout.zones_by_id)} physical zones |",
        f"| CCTV → layout mapping | {'PASS' if not unmapped_db else 'WARN'} | {len(layout.camera_zone_mapping)} camera zones mapped |",
        f"| Heatmap layout alignment | {'PASS' if layout_mapped else 'FAIL'} | keys use `layout:` prefix |",
        f"| Generic names replaced | {'PASS' if not missing_mappings else 'WARN'} | store zone labels on all CCTV polygons |",
        "",
        "## 1. Layout mapping (CCTV → store floor plan)",
        "",
        "| Camera | zone_id | Generic (before) | Store zone (after) | layout_zone_id | DB events |",
        "|--------|---------|------------------|--------------------|----------------|-----------|",
    ]

    for r in sorted(camera_rows, key=lambda x: (x.camera_name, x.zone_id)):
        if r.zone_type == "ignore":
            continue
        lines.append(
            f"| {r.camera_name} | `{r.zone_id}` | {r.generic_name} | **{r.store_name}** | "
            f"`{r.layout_zone_id or '—'}` | {'yes' if r.in_db else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## 2. Zone coordinates",
            "",
            "### 2a. CCTV normalized polygons (pipeline/zones.yaml)",
            "",
            "| Camera | Store zone | Type | Coordinates (normalized 0–1) |",
            "|--------|------------|------|----------------------------|",
        ]
    )
    for r in camera_rows:
        if r.zone_type in ("ignore",) or not r.points:
            continue
        lines.append(
            f"| {r.camera_name} | {r.store_name} | `{r.zone_type}` | `{_format_points(r.points)}` |"
        )

    lines.extend(
        [
            "",
            "### 2b. Floor plan label anchors (from Excel drawing)",
            "",
            "Coordinates normalized to embedded floor-plan image (0=left/top, 1=right/bottom).",
            "",
            "| Label (Excel) | plan_x | plan_y | Revision |",
            "|---------------|-------:|-------:|----------|",
        ]
    )
    for lb in sorted(excel_labels, key=lambda x: (x.revision, x.plan_y, x.plan_x)):
        lines.append(f"| {lb.text} | {lb.plan_x} | {lb.plan_y} | {lb.revision} |")

    lines.extend(
        [
            "",
            "### 2c. Physical layout zones (brigade_road_layout.yaml)",
            "",
            "| layout_zone_id | Label | Section | Plan position |",
            "|----------------|-------|---------|---------------|",
        ]
    )
    for zid, zone in sorted(layout.zones_by_id.items()):
        lines.append(f"| `{zid}` | {zone.label} | {zone.section} | {zone.plan_position or '—'} |")

    lines.extend(
        [
            "",
            "## 3. Heatmap alignment",
            "",
            "| zone_key | zone_label | section | visits | layout match |",
            "|----------|------------|---------|-------:|--------------|",
        ]
    )
    for z in heatmap_zones:
        zkey = z.get("zone_key", "")
        lid = zkey.removeprefix("layout:") if zkey.startswith("layout:") else ""
        match = "yes" if lid in layout.zones_by_id else "no"
        lines.append(
            f"| `{zkey}` | {z.get('zone_label', '')} | {z.get('layout_section') or '—'} | "
            f"{z.get('visit_count', 0)} | {match} |"
        )

    lines.extend(
        [
            "",
            f"**Total heatmap visits:** {heatmap.get('meta', {}).get('total_visits', 0)}",
            f"**Layout remapping active:** {layout_mapped}",
            "",
            "## 4. Missing mappings",
            "",
            "### 4a. Camera zones with DB events but no layout mapping",
            "",
        ]
    )
    if unmapped_db:
        for z in unmapped_db:
            lines.append(f"- `{z}`")
    else:
        lines.append("- None")

    lines.extend(["", "### 4b. Pipeline zones without layout_zone_id", ""])
    if missing_mappings:
        for r in missing_mappings:
            lines.append(f"- `{r.zone_id}` ({r.camera_name}) — generic `{r.generic_name}`")
    else:
        lines.append("- None")

    lines.extend(["", "### 4c. Layout zones without CCTV coverage (plan-only)", ""])
    for zid in layout_without_camera:
        z = layout.zones_by_id[zid]
        lines.append(f"- `{zid}` — **{z.label}** ({z.section})")

    lines.extend(
        [
            "",
            "## 5. Brand bays (Excel Current revision — north/south walls)",
            "",
        ]
    )
    for wall, bays in layout.brand_bays.items():
        lines.append(f"**{wall.replace('_', ' ').title()}:**")
        for bay in bays:
            lines.append(f"- {bay['label']} (`{bay['id']}`)")
        lines.append("")

    overall = (
        bool(excel_labels)
        and layout_mapped
        and not unmapped_db
        and not missing_mappings
    )
    lines.extend(
        [
            "## 6. Validation result",
            "",
            f"**Overall:** {'PASS' if overall else 'PASS WITH WARNINGS' if layout_mapped else 'FAIL'}",
            "",
            "Regenerate: `python scripts/analyze_brigade_layout.py`",
        ]
    )

    out = REPO_ROOT / "docs" / "store_layout_validation_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    if not LAYOUT_XLSX.exists():
        print(f"ERROR: missing {LAYOUT_XLSX}")
        return 1

    layout = load_store_layout()
    excel_labels, excel_meta = _parse_excel_drawing(LAYOUT_XLSX)

    db_zone_ids: set[str] = set()
    try:
        db_zone_ids = asyncio.run(_fetch_db_zone_ids())
    except Exception as exc:
        print(f"WARN: DB zone fetch failed: {exc}")

    camera_rows = _build_camera_rows(layout, db_zone_ids)

    try:
        heatmap = _fetch_heatmap()
    except Exception as exc:
        heatmap = {"zones": [], "meta": {"layout_mapped": False}, "error": str(exc)}

    report_path = _write_report(layout, excel_labels, excel_meta, camera_rows, heatmap, db_zone_ids)

    json_out = REPO_ROOT / "docs" / "evidence" / "brigade_layout_analysis.json"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "excel_labels": [lb.__dict__ for lb in excel_labels],
                "excel_meta": excel_meta,
                "camera_zones": [r.__dict__ for r in camera_rows],
                "heatmap_meta": heatmap.get("meta", {}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Excel labels: {len(excel_labels)}")
    print(f"Camera zones: {len(camera_rows)}")
    print(f"Report: {report_path}")
    print(f"JSON: {json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
