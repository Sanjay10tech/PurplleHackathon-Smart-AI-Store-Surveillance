"""Request-scoped observability context helpers."""

import re
from typing import Any
from uuid import UUID

from starlette.requests import Request

from app.logging_config import bind_context, clear_context

STORE_ID_PATH_PATTERN = re.compile(
    r"/stores/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

TRACE_ID_HEADER = "X-Trace-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"


def extract_store_id_from_path(path: str) -> str | None:
    match = STORE_ID_PATH_PATTERN.search(path)
    return match.group(1) if match else None


def resolve_endpoint(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return str(route.path)
    return request.url.path


def bind_trace_context(
    *,
    trace_id: str,
    endpoint: str | None = None,
    store_id: str | UUID | None = None,
    **extra: Any,
) -> None:
    """Bind standard structured logging fields for the current request."""
    fields: dict[str, Any] = {
        "trace_id": trace_id,
        "correlation_id": trace_id,
    }
    if endpoint is not None:
        fields["endpoint"] = endpoint
    if store_id is not None:
        fields["store_id"] = str(store_id)
    fields.update(extra)
    bind_context(**fields)


def clear_trace_context() -> None:
    clear_context()


def get_request_trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "")


def set_request_observability_state(
    request: Request,
    *,
    trace_id: str,
    endpoint: str,
    store_id: str | None = None,
) -> None:
    request.state.trace_id = trace_id
    request.state.correlation_id = trace_id
    request.state.endpoint = endpoint
    if store_id is not None:
        request.state.store_id = store_id
    if not hasattr(request.state, "event_count"):
        request.state.event_count = 0
