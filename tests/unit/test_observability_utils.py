# PROMPT:
# Generate complete pytest suite — observability context and logging utility unit tests.
#
# CHANGES MADE:
# - Store ID path extraction, route template resolution, and structured log field emission.

import pytest
from starlette.requests import Request
from unittest.mock import MagicMock, patch

from app.observability.context import extract_store_id_from_path, resolve_endpoint
from app.observability.logging_utils import log_http_request


def test_extract_store_id_case_insensitive() -> None:
    store_id = "00000000-0000-0000-0000-000000000101"
    assert extract_store_id_from_path(f"/api/v1/stores/{store_id.upper()}/funnel") == store_id.upper()


def test_log_http_request_emits_required_fields() -> None:
    mock_logger = MagicMock()
    with patch("app.observability.logging_utils.logger", mock_logger):
        log_http_request(
            trace_id="trace-abc",
            endpoint="/api/v1/stores/{store_id}/metrics",
            status_code=200,
            latency_ms=12.5,
            store_id="00000000-0000-0000-0000-000000000101",
            event_count=3,
            method="GET",
        )

    mock_logger.info.assert_called_once()
    kwargs = mock_logger.info.call_args.kwargs
    assert kwargs["trace_id"] == "trace-abc"
    assert kwargs["store_id"] == "00000000-0000-0000-0000-000000000101"
    assert kwargs["endpoint"] == "/api/v1/stores/{store_id}/metrics"
    assert kwargs["latency_ms"] == 12.5
    assert kwargs["event_count"] == 3
    assert kwargs["status_code"] == 200


def test_resolve_endpoint_uses_route_template() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/stores/abc/metrics",
        "headers": [],
        "route": type("Route", (), {"path": "/api/v1/stores/{store_id}/metrics"})(),
    }
    request = Request(scope)
    assert resolve_endpoint(request) == "/api/v1/stores/{store_id}/metrics"
