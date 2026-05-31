import logging
import sys
from typing import Any

import structlog

from app.config import Settings, get_settings


def setup_logging(settings: Settings | None = None) -> None:
    """Configure structlog and stdlib logging for the application."""
    cfg = settings or get_settings()
    log_level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if cfg.use_json_logs:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def bind_context(**kwargs: Any) -> None:
    """Bind key-value pairs to the current structlog context."""
    if "trace_id" in kwargs and "correlation_id" not in kwargs:
        kwargs["correlation_id"] = kwargs["trace_id"]
    elif "correlation_id" in kwargs and "trace_id" not in kwargs:
        kwargs["trace_id"] = kwargs["correlation_id"]
    structlog.contextvars.bind_contextvars(**kwargs)


def bind_trace(**kwargs: Any) -> None:
    """Bind observability fields (trace_id, store_id, endpoint, etc.)."""
    bind_context(**kwargs)


def clear_context() -> None:
    """Clear structlog context variables."""
    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
