#!/usr/bin/env bash
# Run the Store Intelligence detection pipeline (YOLOv11 + ByteTrack).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python}"
CONFIG="${PIPELINE_CONFIG:-pipeline/config.yaml}"
ZONES="${PIPELINE_ZONES:-pipeline/zones.yaml}"

if ! "$PYTHON" -c "import cv2" 2>/dev/null; then
  echo "Installing pipeline dependencies..."
  "$PYTHON" -m pip install -r pipeline/requirements.txt
fi

MODE="${1:-run}"
shift || true

case "$MODE" in
  run)
    exec "$PYTHON" -m pipeline.run --config "$CONFIG" --zones "$ZONES" "$@"
    ;;
  mock)
    exec "$PYTHON" -m pipeline.run --config "$CONFIG" --zones "$ZONES" --mock "$@"
    ;;
  ingest)
    PIPELINE_POST_TO_API=true PIPELINE_PERSIST_SESSIONS=true \
      "$PYTHON" -m pipeline.run --config "$CONFIG" --zones "$ZONES" --ingest --persist-sessions "$@"
    ;;
  all)
    exec "$PYTHON" scripts/process_all_videos.py "$@"
    ;;
  samples)
    "$PYTHON" -c "from pipeline.emit import EventEmitter; EventEmitter.write_sample_files()"
    ;;
  *)
    echo "Usage: $0 {run|mock|ingest|all|samples} [extra pipeline.run args]"
    exit 1
    ;;
esac
