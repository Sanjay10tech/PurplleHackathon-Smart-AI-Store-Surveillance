#!/usr/bin/env python3
"""Validate Brigade Road store layout mapping — delegates to analyze_brigade_layout.py."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.analyze_brigade_layout import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
