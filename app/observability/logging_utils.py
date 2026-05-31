"""Structured logging helpers for HTTP and domain operations."""

from typing import Any

from app.logging_config import get_logger

logger = get_logger(__name__)


def log_http_request(
    *,
    trace_id: str,
    endpoint: str,
    status_code: int,
    latency_ms: float,
    store_id: str | None = None,
    event_count: int = 0,
    method: str | None = None,
    **extra: Any,
) -> None:
    """
    Emit a canonical HTTP access log with required observability fields.

    Fields: trace_id, store_id, endpoint, latency_ms, event_count, status_code
    """
    payload: dict[str, Any] = {
        "trace_id": trace_id,
        "endpoint": endpoint,
        "latency_ms": latency_ms,
        "event_count": event_count,
        "status_code": status_code,
    }
    if store_id is not None:
        payload["store_id"] = store_id
    if method is not None:
        payload["method"] = method
    payload.update(extra)

    logger.info("http_request_completed", **payload)
