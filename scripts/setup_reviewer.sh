#!/usr/bin/env bash
# Purple reviewer one-command setup and validation (Linux/macOS)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Store Intelligence — Reviewer Setup ==="

echo "[1/6] Checking required folders"
for dir in app pipeline tests scripts data/videos docs; do
  if [[ ! -d "$dir" ]]; then
    echo "FAIL: missing directory $dir"
    exit 1
  fi
  echo "  OK $dir"
done

echo "[2/6] Starting Docker stack"
docker compose up --build -d
sleep 5

echo "[3/6] Checking CCTV videos"
if python scripts/setup_videos.py --check; then
  echo "  All 5 videos present"
else
  echo "  WARN: videos missing — copy with:"
  echo "  python scripts/setup_videos.py --source '<CCTV Footage folder>'"
fi

echo "[4/6] Installing Python dependencies"
pip install -e ".[dev,pipeline]" -q

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://si:si@localhost:5432/store_intelligence}"
export API_KEY="${API_KEY:-purple-demo-key}"

echo "[5/6] Running tests + coverage"
python -m pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q

echo "[6/6] Running submission validation"
python scripts/validate_submission.py || python scripts/validate_submission.py --api-only

echo ""
echo "=== Reviewer setup complete ==="
echo "  API docs:     http://localhost:8000/docs"
echo "  Dashboard:    http://localhost:8000/dashboard/"
echo "  API key:      X-API-Key: ${API_KEY}"
echo "  Evidence pack:  docs/REVIEWER_EVIDENCE.md"
echo "  95+ checklist:  95_PLUS_CHECKLIST.md"
