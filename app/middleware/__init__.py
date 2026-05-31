import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.observability.context import (
    CORRELATION_ID_HEADER,
    TRACE_ID_HEADER,
    bind_trace_context,
    clear_trace_context,
    extract_store_id_from_path,
    resolve_endpoint,
    set_request_observability_state,
)
from app.observability.logging_utils import log_http_request


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Bind trace context and emit structured request logs.

    Required log fields: trace_id, store_id, endpoint, latency_ms,
    event_count, status_code.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        clear_trace_context()

        trace_id = (
            request.headers.get(TRACE_ID_HEADER)
            or request.headers.get(CORRELATION_ID_HEADER)
            or str(uuid.uuid4())
        )
        endpoint = resolve_endpoint(request)
        store_id = extract_store_id_from_path(request.url.path)

        set_request_observability_state(
            request,
            trace_id=trace_id,
            endpoint=endpoint,
            store_id=store_id,
        )
        bind_trace_context(
            trace_id=trace_id,
            endpoint=endpoint,
            store_id=store_id,
            service="store-intelligence-api",
        )

        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        state_store_id = getattr(request.state, "store_id", None) or store_id
        event_count = int(getattr(request.state, "event_count", 0) or 0)

        log_http_request(
            trace_id=trace_id,
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
            store_id=state_store_id,
            event_count=event_count,
            method=request.method,
        )

        response.headers[TRACE_ID_HEADER] = trace_id
        response.headers[CORRELATION_ID_HEADER] = trace_id
        return response


# Backward-compatible aliases
CorrelationIdMiddleware = ObservabilityMiddleware
RequestLoggingMiddleware = ObservabilityMiddleware
