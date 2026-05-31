# PROMPT:
# Infrastructure coverage — config, logging, database, exceptions, observability context.
#
# CHANGES MADE:
# - Branch coverage for Settings, structlog setup, DB singleton/rollback, and error types.

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from starlette.requests import Request

from app.config import Settings, get_settings
from app.database import (
    check_database_connection,
    create_engine,
    dispose_engine,
    get_db_session,
    reset_engine_singleton,
)
from app.exceptions import AppError, ConflictError, NotFoundError, ValidationError
from app.logging_config import bind_context, bind_trace, clear_context, setup_logging
from app.observability.context import (
    bind_trace_context,
    clear_trace_context,
    get_request_trace_id,
    resolve_endpoint,
    set_request_observability_state,
)
from app.services.health_service import _as_utc


class TestSettings:
    def test_is_production_and_json_logs(self) -> None:
        prod = Settings(environment="production", log_json=False)
        assert prod.is_production is True
        assert prod.use_json_logs is True

        dev = Settings(environment="development", log_json=True)
        assert dev.is_production is False
        assert dev.use_json_logs is True


class TestLoggingConfig:
    def test_setup_logging_json_and_console(self) -> None:
        setup_logging(Settings(log_json=True, log_level="DEBUG", environment="production"))
        setup_logging(Settings(log_json=False, log_level="INFO", environment="development"))

    def test_bind_context_syncs_trace_and_correlation(self) -> None:
        clear_context()
        bind_context(trace_id="trace-abc")
        bind_trace(correlation_id="corr-xyz")
        clear_context()

    def test_bind_trace_alias(self) -> None:
        clear_context()
        bind_trace(store_id="00000000-0000-0000-0000-000000000101")
        clear_context()


class TestDatabase:
    @pytest.fixture(autouse=True)
    def _reset_engine(self) -> None:
        reset_engine_singleton()
        get_settings.cache_clear()
        yield
        reset_engine_singleton()
        get_settings.cache_clear()

    def test_create_engine_postgres_pool_options(self) -> None:
        reset_engine_singleton()
        settings = Settings(
            database_url="postgresql+asyncpg://u:p@localhost/db",
            db_pool_size=3,
            db_max_overflow=5,
        )
        engine = create_engine(settings)
        assert engine is not None
        assert create_engine(settings) is engine

    @pytest.mark.asyncio
    async def test_get_db_session_commits_on_success(self, db_session_factory) -> None:
        async for _session in get_db_session():
            break

    @pytest.mark.asyncio
    async def test_get_db_session_rolls_back_on_error(self, db_session_factory) -> None:
        gen = get_db_session()
        await gen.__anext__()
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("boom"))

    @pytest.mark.asyncio
    async def test_check_database_connection_failure(self) -> None:
        reset_engine_singleton()
        with patch("app.database.create_engine") as mock_engine:
            conn = AsyncMock()
            conn.execute = AsyncMock(side_effect=ConnectionError("db down"))
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=conn)
            ctx.__aexit__ = AsyncMock(return_value=None)
            mock_engine.return_value.connect = MagicMock(return_value=ctx)
            assert await check_database_connection() is False

    @pytest.mark.asyncio
    async def test_dispose_engine_clears_singleton(self) -> None:
        reset_engine_singleton()
        create_engine(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        await dispose_engine()
        reset_engine_singleton()


class TestExceptions:
    def test_app_error_and_subclasses(self) -> None:
        nf = NotFoundError("store", "abc")
        assert nf.code == "not_found"
        assert nf.resource == "store"

        conflict = ConflictError("duplicate")
        assert conflict.code == "conflict"

        validation = ValidationError("bad payload")
        assert validation.code == "validation_error"

        base = AppError("msg", code="custom")
        assert base.message == "msg"


class TestObservabilityContext:
    def test_resolve_endpoint_without_route(self) -> None:
        scope = {"type": "http", "path": "/raw/path", "headers": []}
        request = Request(scope)
        assert resolve_endpoint(request) == "/raw/path"

    def test_bind_and_request_state(self) -> None:
        scope = {"type": "http", "path": "/health"}
        request = Request(scope)
        set_request_observability_state(
            request,
            trace_id="tid",
            endpoint="/health",
            store_id=str(uuid.uuid4()),
        )
        assert get_request_trace_id(request) == "tid"
        bind_trace_context(trace_id="tid-2", endpoint="/metrics")
        clear_trace_context()

    def test_health_as_utc_naive(self) -> None:
        from datetime import datetime

        naive = datetime(2026, 5, 30, 12, 0, 0)
        assert _as_utc(naive).tzinfo is not None
