"""End-to-end submission validation — API, pipeline, BI endpoints."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_BASE = "http://localhost:8000"
STORE_ID = "00000000-0000-0000-0000-000000000101"
DEFAULT_MAX_FRAMES = int(os.environ.get("VALIDATION_MAX_FRAMES", "25"))
DEFAULT_INGEST_CAMERAS = ("CAM 3", "CAM 1", "CAM 5")


def _api_headers() -> dict[str, str]:
    key = os.environ.get("API_KEY", "purple-demo-key")
    return {"X-API-Key": key}


class Check:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = False
        self.detail = ""

    def pass_(self, detail: str = "") -> None:
        self.ok = True
        self.detail = detail

    def fail(self, detail: str) -> None:
        self.ok = False
        self.detail = detail


def http_get(path: str, *, retries: int = 3) -> tuple[int, dict]:
    last_exc: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(f"{API_BASE}{path}", headers=_api_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode())
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < retries:
                time.sleep(2)
    raise last_exc  # type: ignore[misc]


def run_checks(
    *,
    skip_videos: bool = False,
    skip_pipeline: bool = False,
    use_mock: bool = False,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> list[Check]:
    results: list[Check] = []

    if not skip_videos:
        c = Check("data/videos present")
        missing = [
            f"CAM {i}.mp4"
            for i in range(1, 6)
            if not (REPO_ROOT / "data" / "videos" / f"CAM {i}.mp4").is_file()
        ]
        if missing:
            c.fail(f"missing: {', '.join(missing)}")
        else:
            c.pass_("5 MP4 files found")
        results.append(c)

    c = Check("GET /health")
    try:
        status, body = http_get("/health")
        if status == 200 and body.get("checks", {}).get("database") == "up":
            c.pass_(f"status={body.get('status')}, feed={body.get('checks', {}).get('feed')}")
        else:
            c.fail(str(body))
    except Exception as exc:
        c.fail(str(exc))
    results.append(c)

    c = Check("GET /health/ready")
    try:
        status, body = http_get("/health/ready")
        if status == 200 and body.get("status") == "ready":
            c.pass_("database up")
        else:
            c.fail(str(body))
    except Exception as exc:
        c.fail(str(exc))
    results.append(c)

    if not skip_pipeline:
        mode_label = "mock trajectories" if use_mock else "real YOLO"
        c = Check(f"pipeline ingest ({mode_label})")
        ingest_env = os.environ.copy()
        ingest_env["API_KEY"] = os.environ.get("API_KEY", "purple-demo-key")
        per_cam_timeout = 180 if use_mock else int(os.environ.get("VALIDATION_YOLO_TIMEOUT", "900"))
        try:
            lines_out: list[str] = []
            for cam in DEFAULT_INGEST_CAMERAS:
                cmd = [
                    sys.executable,
                    "-m",
                    "pipeline.run",
                    "--ingest",
                    "--persist-sessions",
                    "--camera",
                    cam,
                    "--max-frames",
                    str(max_frames),
                ]
                if use_mock:
                    cmd.append("--mock")
                proc = subprocess.run(
                    cmd,
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=per_cam_timeout,
                    env=ingest_env,
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"{cam}: {(proc.stderr or proc.stdout)[-500:]}"
                    )
                tail = proc.stdout.strip().splitlines()
                if tail:
                    lines_out.append(f"{cam}: {tail[-1][:80]}")
            detail = "; ".join(lines_out)[:240] if lines_out else f"3 cameras x {max_frames} frames"
            if not use_mock:
                detail = f"yolo11n.pt · {detail}"
            c.pass_(detail)
        except Exception as exc:
            c.fail(str(exc))
        results.append(c)

        c = Check("metrics available (projector or script)")
        try:
            proc = subprocess.run(
                [sys.executable, "scripts/project_demo_metrics.py"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                c.pass_(proc.stdout.strip())
            else:
                c.fail(proc.stderr or proc.stdout)
        except Exception as exc:
            c.fail(str(exc))
        results.append(c)

    time.sleep(1)

    endpoints = [
        ("GET /metrics", f"/api/v1/stores/{STORE_ID}/metrics"),
        ("GET /funnel", f"/api/v1/stores/{STORE_ID}/funnel"),
        ("GET /heatmap", f"/api/v1/stores/{STORE_ID}/heatmap"),
        ("GET /anomalies", f"/api/v1/stores/{STORE_ID}/anomalies"),
    ]
    for label, path in endpoints:
        c = Check(label)
        try:
            status, body = http_get(path)
            if status != 200:
                c.fail(f"HTTP {status}")
            elif label.endswith("/metrics"):
                series = body.get("series") or []
                meta = body.get("meta") or {}
                if series or meta.get("source") == "store_metrics":
                    c.pass_(f"series_points={len(series)}, source={meta.get('source')}")
                elif meta.get("partial"):
                    c.pass_(f"partial ok: {meta.get('message', '')[:60]}")
                else:
                    c.fail("empty metrics")
            elif label.endswith("/funnel"):
                stages = body.get("stages") or []
                for stage in stages:
                    rate = stage.get("conversion_rate")
                    if rate is not None and not (0 <= rate <= 1):
                        c.fail(f"invalid conversion_rate={rate} for {stage.get('stage')}")
                        break
                else:
                    entry = next((s for s in stages if s.get("stage") == "ENTRY"), None)
                    count = entry.get("count", 0) if entry else 0
                    c.pass_(f"ENTRY count={count}, rates bounded") if stages else c.fail("no stages")
            elif label.endswith("/heatmap"):
                zones = body.get("zones") or []
                c.pass_(f"zones={len(zones)}") if zones else c.pass_("empty heatmap (partial ok)")
            else:
                c.pass_(f"items={len(body.get('items') or body.get('anomalies') or [])}")
        except Exception as exc:
            c.fail(str(exc))
        results.append(c)

    c = Check("GET /health after checks")
    try:
        status, body = http_get("/health")
        feed = body.get("checks", {}).get("feed")
        if status == 200:
            c.pass_(f"status={body.get('status')}, feed={feed}")
        else:
            c.fail(str(body))
    except Exception as exc:
        c.fail(str(exc))
    results.append(c)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Store Intelligence submission")
    parser.add_argument("--skip-pipeline", action="store_true", help="Skip video + pipeline checks")
    parser.add_argument("--api-only", action="store_true", help="API/BI checks only (CI mode)")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock trajectories instead of real YOLO (optional dev/CI shortcut)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=DEFAULT_MAX_FRAMES,
        help=f"Max frames per camera for pipeline ingest (default: {DEFAULT_MAX_FRAMES})",
    )
    args = parser.parse_args()

    skip_videos = args.skip_pipeline or args.api_only
    skip_pipeline = args.skip_pipeline or args.api_only

    mode_note = "mock mode" if args.mock else "real YOLO default"
    print(f"Store Intelligence — submission validation ({mode_note})\n")
    results = run_checks(
        skip_videos=skip_videos,
        skip_pipeline=skip_pipeline,
        use_mock=args.mock,
        max_frames=args.max_frames,
    )
    failed = sum(1 for c in results if not c.ok)
    for check in results:
        mark = "PASS" if check.ok else "FAIL"
        print(f"[{mark}] {check.name}")
        if check.detail:
            print(f"       {check.detail}")
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
