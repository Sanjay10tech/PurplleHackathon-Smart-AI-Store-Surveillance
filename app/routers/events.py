from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import get_correlation_id, get_event_ingestion_service
from app.exceptions import ValidationError
from app.security import require_api_key
from app.schemas.common import ProblemDetail
from app.schemas.events import (
    BatchIngestSummary,
    EventBatchIngestRequest,
    EventIngestRequest,
    MAX_BATCH_SIZE,
)
from app.services.event_ingestion_service import EventIngestionService

router = APIRouter(
    prefix="/events",
    tags=["events"],
    dependencies=[Depends(require_api_key)],
)


def _bind_ingest_observability(
    request: Request,
    *,
    store_id: str | None,
    event_count: int,
) -> None:
    request.state.event_count = event_count
    if store_id is not None:
        request.state.store_id = store_id


def _resolve_http_status(summary: BatchIngestSummary) -> int:
    if summary.rejected == summary.total:
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    if summary.rejected > 0:
        return status.HTTP_207_MULTI_STATUS
    return status.HTTP_202_ACCEPTED


@router.post(
    "/ingest",
    summary="Ingest domain events (single or batch)",
    description=(
        "Accepts a single event object or `{ \"events\": [...] }` batch (max 500). "
        "Returns 202 when all succeed, 207 on partial success, 422 when all rejected."
    ),
    responses={
        202: {"description": "All events accepted or deduplicated"},
        207: {"description": "Partial success — see per-item results"},
        422: {"description": "All events rejected or envelope invalid"},
    },
)
async def ingest_events(
    request: Request,
    service: Annotated[EventIngestionService, Depends(get_event_ingestion_service)],
    correlation_id: Annotated[str, Depends(get_correlation_id)],
) -> JSONResponse:
    try:
        payload: Any = await request.json()
    except Exception as exc:
        raise ValidationError("Request body must be valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")

    is_batch = "events" in payload

    try:
        if is_batch:
            batch = EventBatchIngestRequest.model_validate(payload)
            _bind_ingest_observability(
                request,
                store_id=str(batch.events[0].store_id) if batch.events else None,
                event_count=len(batch.events),
            )
            response = await service.ingest_batch(batch, correlation_id)
            return JSONResponse(
                status_code=_resolve_http_status(response.summary),
                content=response.model_dump(mode="json"),
            )

        single = EventIngestRequest.model_validate(payload)
        _bind_ingest_observability(
            request,
            store_id=str(single.store_id),
            event_count=1,
        )
        result = await service.ingest(single, correlation_id)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=result.model_dump(mode="json"),
        )
    except PydanticValidationError as exc:
        errors = [
            {"field": ".".join(str(loc) for loc in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        detail = "Request validation failed"
        error_type = "https://store-intelligence/errors/validation"
        for err in exc.errors():
            if err.get("type") == "too_long" and err.get("loc") == ("events",):
                detail = f"Maximum batch size is {MAX_BATCH_SIZE} events"
                error_type = "https://store-intelligence/errors/batch-too-large"

        problem = ProblemDetail(
            type=error_type,
            title="Validation Error",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
            instance=str(request.url.path),
            correlation_id=correlation_id,
            errors=errors,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=problem.model_dump(exclude_none=True),
            media_type="application/problem+json",
        )
