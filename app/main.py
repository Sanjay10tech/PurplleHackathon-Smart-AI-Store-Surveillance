from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import create_engine, create_session_factory, dispose_engine
from app.exceptions import AppError, ConflictError, NotFoundError, ValidationError
from app.logging_config import get_logger, setup_logging
from app.middleware import ObservabilityMiddleware
from app.routers import events, health, reviewer, stores, ws
from app.schemas.common import ProblemDetail
from app.security import UnauthorizedError

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return _problem_response(
            request,
            status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=exc.message,
            error_type="https://store-intelligence/errors/not-found",
        )

    @app.exception_handler(ValidationError)
    async def validation_app_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return _problem_response(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation Error",
            detail=exc.message,
            error_type="https://store-intelligence/errors/validation",
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return _problem_response(
            request,
            status.HTTP_409_CONFLICT,
            title="Conflict",
            detail=exc.message,
            error_type="https://store-intelligence/errors/conflict",
        )

    @app.exception_handler(UnauthorizedError)
    async def unauthorized_handler(request: Request, exc: UnauthorizedError) -> JSONResponse:
        return _problem_response(
            request,
            status.HTTP_401_UNAUTHORIZED,
            title="Unauthorized",
            detail=exc.message,
            error_type="https://store-intelligence/errors/unauthorized",
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _problem_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal Error",
            detail=exc.message,
            error_type="https://store-intelligence/errors/internal",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = [
            {"field": ".".join(str(loc) for loc in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        body = ProblemDetail(
            type="https://store-intelligence/errors/validation",
            title="Validation Error",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request validation failed",
            instance=str(request.url.path),
            correlation_id=_correlation_id(request),
            trace_id=_trace_id(request),
            errors=errors,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=body.model_dump(exclude_none=True),
            media_type="application/problem+json",
        )


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None) or getattr(
        request.state, "correlation_id", None
    )


def _correlation_id(request: Request) -> str | None:
    return _trace_id(request)


def _problem_response(
    request: Request,
    status_code: int,
    title: str,
    detail: str,
    error_type: str,
) -> JSONResponse:
    body = ProblemDetail(
        type=error_type,
        title=title,
        status=status_code,
        detail=detail,
        instance=str(request.url.path),
        correlation_id=_correlation_id(request),
        trace_id=_trace_id(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings)
    create_engine(settings)
    create_session_factory()
    logger.info("application_startup", environment=settings.environment)

    async def _run_bootstrap() -> None:
        if settings.cctv_auto_bootstrap:
            try:
                from app.services.cctv_bootstrap import bootstrap_cctv_events

                cctv_stats = await bootstrap_cctv_events(settings)
                logger.info("cctv_bootstrap_complete", **cctv_stats)
            except Exception as exc:
                logger.warning("cctv_bootstrap_failed", error=str(exc))
        if settings.pos_auto_ingest:
            try:
                from app.services.pos_bootstrap import bootstrap_pos_ingestion

                pos_stats = await bootstrap_pos_ingestion(settings)
                logger.info("pos_bootstrap_complete", **pos_stats)
            except Exception as exc:
                logger.warning("pos_bootstrap_failed", error=str(exc))
        try:
            from app.services.reviewer_journey_bootstrap import ensure_reviewer_journey_metrics

            journey_stats = await ensure_reviewer_journey_metrics(settings)
            logger.info("reviewer_journey_metrics_ready", **journey_stats)
        except Exception as exc:
            logger.warning("reviewer_journey_metrics_failed", error=str(exc))

    await _run_bootstrap()
    yield
    await dispose_engine()
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Store Intelligence API",
        description=(
            "CCTV-to-retail-analytics platform\n\n"
            "## Purple Tech reviewer quick-start\n\n"
            "**Demo store ID:** `00000000-0000-0000-0000-000000000101`\n\n"
            "**API key:** `purple-demo-key` (header `X-API-Key`) — click **Authorize** above\n\n"
            "| Endpoint | Path |\n"
            "|----------|------|\n"
            "| Health | `GET /health` (no auth) |\n"
            "| Reviewer proof | `GET /reviewer` (no auth) |\n"
            "| **Reviewer API guide** | `GET /reviewer/api` (no auth — all curl examples) |\n"
            "| Metrics | `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/metrics` |\n"
            "| Funnel | `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/funnel` |\n"
            "| Heatmap | `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/heatmap` |\n"
            "| Anomalies | `GET /api/v1/stores/00000000-0000-0000-0000-000000000101/anomalies` |\n"
            "| Dashboard | http://localhost:8000/dashboard/ |\n\n"
            "Do **not** use `{id}` placeholders — use the demo store UUID above."
        ),
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ObservabilityMiddleware)

    register_exception_handlers(app)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/")

    app.include_router(reviewer.router)
    app.include_router(health.router)
    app.include_router(events.router, prefix=settings.api_prefix)
    app.include_router(stores.router, prefix=settings.api_prefix)
    app.include_router(ws.router)

    dashboard_dir = Path(__file__).resolve().parents[1] / "dashboard"
    if dashboard_dir.is_dir():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    evidence_dir = Path(__file__).resolve().parents[1] / "docs" / "evidence"
    if evidence_dir.is_dir():
        app.mount(
            "/evidence-assets",
            StaticFiles(directory=str(evidence_dir)),
            name="evidence-assets",
        )

    return app


app = create_app()
