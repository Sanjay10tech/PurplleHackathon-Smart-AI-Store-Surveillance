"""Docker container entrypoint: wait for DB, migrate, seed, start API."""

from __future__ import annotations

import os
import subprocess
import sys


def run_command(command: list[str]) -> None:
    print(f"[entrypoint] running: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def build_uvicorn_command() -> list[str]:
    port = os.environ.get("API_PORT", "8000")
    workers = int(os.environ.get("UVICORN_WORKERS", "1"))
    command = [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    if workers > 1:
        command.extend(["--workers", str(workers)])
    return command


def main() -> None:
    print("[entrypoint] waiting for database...", flush=True)
    run_command([sys.executable, "scripts/wait_for_database.py"])

    print("[entrypoint] running alembic migrations...", flush=True)
    run_command(["alembic", "upgrade", "head"])

    if os.environ.get("SEED_DEMO_DATA", "true").lower() in {"1", "true", "yes"}:
        print("[entrypoint] seeding demo store (idempotent)...", flush=True)
        run_command([sys.executable, "scripts/seed_dev_data.py"])

    if os.environ.get("CCTV_AUTO_BOOTSTRAP", "true").lower() in {"1", "true", "yes"}:
        print("[entrypoint] bootstrapping CCTV vision events (idempotent)...", flush=True)
        try:
            run_command([sys.executable, "scripts/bootstrap_cctv.py"])
        except subprocess.CalledProcessError:
            print("[entrypoint] CCTV bootstrap skipped (file missing or already loaded)", flush=True)

    if os.environ.get("POS_AUTO_INGEST", "true").lower() in {"1", "true", "yes"}:
        print("[entrypoint] ingesting POS CSV (idempotent)...", flush=True)
        try:
            run_command([sys.executable, "scripts/ingest_pos_csv.py"])
        except subprocess.CalledProcessError:
            print("[entrypoint] POS ingest skipped (CSV missing or already loaded)", flush=True)

    if os.environ.get("JOURNEY_AUTO_MATERIALIZE", "true").lower() in {"1", "true", "yes"}:
        print("[entrypoint] materializing sessions + POS linkage...", flush=True)
        try:
            run_command([sys.executable, "scripts/materialize_journey_metrics.py"])
        except subprocess.CalledProcessError:
            print("[entrypoint] journey materialization skipped", flush=True)

    command = sys.argv[1:] if len(sys.argv) > 1 else build_uvicorn_command()
    if command and command[0] == "uvicorn" and "--workers" not in command:
        command = build_uvicorn_command()

    print(f"[entrypoint] starting: {' '.join(command)}", flush=True)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
