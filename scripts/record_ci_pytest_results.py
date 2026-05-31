#!/usr/bin/env python3
"""Parse pytest CI log and write docs/evidence/ci_pytest.json."""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "docs" / "evidence"


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    log_path = EVIDENCE / "pytest.log"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""

    passed = re.search(r"(\d+) passed", log)
    cov = re.search(r"Total coverage:\s*([\d.]+)%", log, re.S)

    payload: dict[str, object] = {
        "success": " failed" not in log and "ERROR" not in log.splitlines()[-3:],
        "passed": int(passed.group(1)) if passed else None,
        "coverage_pct": float(cov.group(1)) if cov else None,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }

    xml = EVIDENCE / "coverage.xml"
    if xml.is_file():
        root = ET.parse(xml).getroot()
        payload["lines_valid"] = int(root.get("lines-valid", 0))
        payload["lines_covered"] = int(root.get("lines-covered", 0))
        if payload.get("coverage_pct") is None:
            payload["coverage_pct"] = round(float(root.get("line-rate", 0)) * 100, 2)

    junit = EVIDENCE / "junit.xml"
    if junit.is_file():
        suite = ET.parse(junit).getroot()
        if suite.tag != "testsuite":
            found = suite.find("testsuite")
            suite = found if found is not None else suite
        payload["tests"] = int(suite.get("tests", 0))
        payload["failures"] = int(suite.get("failures", 0))

    (EVIDENCE / "ci_pytest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
