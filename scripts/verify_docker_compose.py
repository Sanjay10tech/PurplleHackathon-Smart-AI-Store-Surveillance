#!/usr/bin/env python3
"""Verify docker compose stack: build, health, and API validation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_BASE = os.environ.get("COMPOSE_API_BASE", "http://localhost:8000")
MAX_WAIT_SECONDS = int(os.environ.get("COMPOSE_VERIFY_TIMEOUT", "180"))
STORE_ID = "00000000-0000-0000-0000-000000000101"


def _run(cmd: list[str], *, check: bool = True, **kwargs) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        **kwargs,
    )


def _http_get(path: str) -> tuple[int | None, dict | str]:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"X-API-Key": os.environ.get("API_KEY", "purple-demo-key")},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body[:200]
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, str(exc)


def _http_ok(path: str) -> tuple[bool, str]:
    status, body = _http_get(path)
    if status != 200:
        return False, body if isinstance(body, str) else str(body)[:200]
    return True, body if isinstance(body, str) else json.dumps(body)[:200]


def _wait_for_compose_healthy() -> dict:
    deadline = time.time() + MAX_WAIT_SECONDS
    last_ps = ""
    while time.time() < deadline:
        ps = _run(["docker", "compose", "ps", "--format", "json"], check=False)
        last_ps = ps.stdout.strip() or ps.stderr.strip()
        health_ok, _ = _http_ok("/health/ready")
        live_ok, live_body = _http_ok("/health")
        if health_ok and live_ok:
            return {
                "healthy": True,
                "health_body": live_body,
                "compose_ps": last_ps,
                "elapsed_s": round(MAX_WAIT_SECONDS - (deadline - time.time()), 1),
            }
        time.sleep(5)
    return {"healthy": False, "compose_ps": last_ps, "elapsed_s": MAX_WAIT_SECONDS}


def _metrics_ready() -> bool:
    status, body = _http_get(f"/api/v1/stores/{STORE_ID}/metrics?metric=visitor.count")
    if status != 200 or not isinstance(body, dict):
        return False
    series = body.get("series") or []
    meta = body.get("meta") or {}
    return bool(series) or meta.get("source") == "store_metrics" or bool(meta.get("partial"))


def _wait_for_analytics_ready() -> dict:
    deadline = time.time() + min(60, MAX_WAIT_SECONDS)
    while time.time() < deadline:
        if _metrics_ready():
            return {"analytics_ready": True}
        time.sleep(3)
    return {"analytics_ready": False}


def verify(*, keep_running: bool = False) -> dict:
    env = os.environ.copy()
    env.setdefault("API_KEY", "purple-demo-key")
    env.setdefault("API_KEY_REQUIRED", "true")
    env.setdefault("SEED_DEMO_DATA", "true")

    _run(["docker", "compose", "down", "-v"], check=False)

    up = _run(["docker", "compose", "up", "--build", "-d", "postgres", "api"], env=env, check=False)
    if up.returncode != 0:
        return {
            "success": False,
            "step": "compose_up",
            "stderr": (up.stderr or up.stdout)[-500:],
        }

    wait = _wait_for_compose_healthy()
    if not wait.get("healthy"):
        _run(["docker", "compose", "logs", "api", "--tail", "80"], check=False)
        if not keep_running:
            _run(["docker", "compose", "down", "-v"], check=False)
        return {"success": False, "step": "health_wait", **wait}

    analytics = _wait_for_analytics_ready()
    if not analytics.get("analytics_ready"):
        _run(["docker", "compose", "logs", "api", "--tail", "80"], check=False)
        if not keep_running:
            _run(["docker", "compose", "down", "-v"], check=False)
        return {"success": False, "step": "analytics_wait", **wait, **analytics}

    validation = _run(
        [sys.executable, "scripts/validate_submission.py", "--api-only"],
        env=env,
        check=False,
    )
    validation_ok = validation.returncode == 0
    passed_line = next(
        (line for line in validation.stdout.splitlines() if "checks passed" in line),
        "",
    )

    if not keep_running:
        _run(["docker", "compose", "down", "-v"], check=False)

    return {
        "success": validation_ok,
        "step": "validation" if validation_ok else "validation_failed",
        "api_base": API_BASE,
        "compose_ps": wait.get("compose_ps"),
        "validation_summary": passed_line,
        "validation_stdout_tail": validation.stdout.strip().splitlines()[-12:],
        "validation_stderr_tail": validation.stderr.strip().splitlines()[-8:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Docker Compose deployment")
    parser.add_argument("--keep-running", action="store_true", help="Leave stack up after verify")
    parser.add_argument(
        "--write-json",
        type=Path,
        default=REPO_ROOT / "docs" / "evidence" / "ci_docker_compose.json",
    )
    args = parser.parse_args()

    result = verify(keep_running=args.keep_running)
    payload = {
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "api_base": API_BASE,
        **result,
    }
    args.write_json.parent.mkdir(parents=True, exist_ok=True)
    args.write_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))

    if result.get("success"):
        print(f"Docker Compose verification PASSED -> {args.write_json}")
        return 0
    print(f"Docker Compose verification FAILED at step={result.get('step')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
