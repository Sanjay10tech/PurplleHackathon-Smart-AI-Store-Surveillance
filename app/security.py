"""API key authentication for ingest and analytics routes."""

from typing import Annotated

from fastapi import Depends, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings
from app.exceptions import AppError

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

DEMO_REVIEWER_API_KEY = "purple-demo-key"


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Invalid or missing API key") -> None:
        super().__init__(message, code="unauthorized")


def _accepted_keys(settings: Settings) -> set[str]:
    keys: set[str] = set()
    if settings.reviewer_mode:
        keys.add(DEMO_REVIEWER_API_KEY)
    configured = (settings.api_key or "").strip()
    if configured:
        keys.add(configured)
    if not keys:
        keys.add(DEMO_REVIEWER_API_KEY)
    return keys


async def require_api_key(
    x_api_key: Annotated[str | None, Depends(_api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Reject requests when API key auth is enabled and the key is missing or wrong."""
    if not settings.api_key_required:
        return
    configured = (settings.api_key or "").strip()
    if not configured and not settings.reviewer_mode:
        return
    accepted = _accepted_keys(settings)
    if not x_api_key or x_api_key.strip() not in accepted:
        hint = settings.effective_api_key if settings.reviewer_mode else "configured API_KEY"
        raise UnauthorizedError(
            f"Invalid or missing API key — send header X-API-Key: {hint}"
        )


def api_key_headers(settings: Settings | None = None) -> dict[str, str]:
    """Headers for pipeline / validation scripts."""
    cfg = settings or get_settings()
    key = cfg.effective_api_key
    if key:
        return {"X-API-Key": key}
    return {}
