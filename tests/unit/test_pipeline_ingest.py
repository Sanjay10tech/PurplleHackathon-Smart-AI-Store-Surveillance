# PROMPT:
# Pipeline ingest validation — EventIngestRequest alignment and sample file checks.
#
# CHANGES MADE:
# - Validates pipeline event dicts and sample JSON files against ingest schema.

"""Pipeline integration tests for ingest validation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.events import EventIngestRequest
from pipeline.emit import EventBuilder, EventEmitter
from pipeline.ingest import validate_event_dict, validate_event_dicts


def test_validate_pipeline_event_dict() -> None:
    store_id = "00000000-0000-0000-0000-000000000101"
    raw = {
        "event_type": "vision.frame.processed",
        "schema_version": "1.0.0",
        "tenant_id": store_id,
        "store_id": store_id,
        "occurred_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "correlation_id": "test",
        "idempotency_key": "frame-1",
        "aggregate": {"type": "pipeline_run", "id": str(uuid.uuid4())},
        "payload": {"store_id": store_id, "frame_index": 1},
    }
    model = validate_event_dict(raw)
    assert isinstance(model, EventIngestRequest)
    assert model.event_type == "vision.frame.processed"


def test_sample_files_pass_validation() -> None:
    paths = EventEmitter.write_sample_files()
    for name in ("vision.frame.processed.json", "vision.zone.entered.json", "batch_ingest.json"):
        if name == "batch_ingest.json":
            import json

            events = json.loads(paths[name].read_text(encoding="utf-8"))["events"]
        else:
            import json

            events = [json.loads(paths[name].read_text(encoding="utf-8"))]
        validated, errors = validate_event_dicts(events)
        assert not errors
        assert len(validated) == len(events)
