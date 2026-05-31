#!/usr/bin/env python3
"""CLI wrapper for CCTV bootstrap (Docker entrypoint + local dev)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def _main() -> int:
    from app.database import create_engine, dispose_engine, reset_engine_singleton
    from app.services.cctv_bootstrap import bootstrap_cctv_events

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = url
    reset_engine_singleton()
    create_engine()

    stats = await bootstrap_cctv_events()
    await dispose_engine()
    print(f"CCTV bootstrap: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
