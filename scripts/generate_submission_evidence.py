"""Collect submission evidence artifacts for Purple reviewers."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"


def _run(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
    }


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    bundle: dict = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "repository": str(REPO_ROOT),
        "steps": [],
    }

    bundle["steps"].append(_run([sys.executable, "-m", "pytest", "tests/", "-q", "--import-mode=importlib", "--cov=app", "--cov-branch"]))
    bundle["steps"].append(_run([sys.executable, "scripts/setup_videos.py", "--check"]))

    yolo_path = REPO_ROOT / "docs" / "evidence" / "yolo_evidence.json"
    if not yolo_path.is_file():
        bundle["steps"].append(_run([sys.executable, "scripts/generate_yolo_evidence.py"]))
    bundle["yolo_evidence"] = json.loads(yolo_path.read_text(encoding="utf-8")) if yolo_path.is_file() else None

    out = EVIDENCE_DIR / "submission_bundle.json"
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"Evidence bundle written to {out}")


if __name__ == "__main__":
    main()
