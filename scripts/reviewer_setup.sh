#!/usr/bin/env bash
# One-command reviewer setup (Linux/macOS)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Starting Docker stack"
docker compose up --build -d

echo "==> Checking CCTV videos"
if ! python scripts/setup_videos.py --check 2>/dev/null; then
  echo "WARN: Copy videos with: python scripts/setup_videos.py --source '<CCTV Footage path>'"
fi

echo "==> Installing Python deps"
pip install -e ".[dev,pipeline]" -q

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://si:si@localhost:5432/store_intelligence}"
export API_KEY="${API_KEY:-purple-demo-key}"

echo "==> Running submission validation"
python scripts/validate_submission.py

echo "==> Running test suite"
python -m pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q

echo "==> Done. Dashboard: http://localhost:8000/dashboard/"
