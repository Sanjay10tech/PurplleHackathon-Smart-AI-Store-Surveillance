#!/usr/bin/env python3
"""Parse validation CI log and write docs/evidence/ci_validation.json."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "docs" / "evidence"


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    log = EVIDENCE / "validation.log"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    summary = next((line for line in text.splitlines() if "checks passed" in line), "")

    payload = {
        "success": "0/" not in summary and "checks passed" in summary,
        "summary": summary.strip(),
        "stdout_tail": text.strip().splitlines()[-12:],
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }
    (EVIDENCE / "ci_validation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
