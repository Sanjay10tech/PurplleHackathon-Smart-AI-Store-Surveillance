"""Batch event ingestion with validation, deduplication, and partial success."""

import uuid

from app.config import Settings
from app.logging_config import get_logger
from app.models import Event
from app.repositories.interfaces import EventRepositoryProtocol
from app.schemas.events import (
    BatchIngestSummary,
    EventBatchIngestRequest,
    EventBatchIngestResponse,
    EventIngestItemResult,
    EventIngestRequest,
    EventIngestResponse,
    IngestOutcome,
)
from app.services.event_validation_service import EventValidationServiceProtocol
from app.services.interfaces import EventIngestionServiceProtocol
from app.services.metrics_projector_service import MetricsProjectorService

logger = get_logger(__name__)


class EventIngestionService(EventIngestionServiceProtocol):
    def __init__(
        self,
        event_repository: EventRepositoryProtocol,
        validation_service: EventValidationServiceProtocol,
        settings: Settings,
        metrics_projector: MetricsProjectorService | None = None,
    ) -> None:
        self._events = event_repository
        self._validator = validation_service
        self._settings = settings
        self._metrics_projector = metrics_projector

    async def ingest(self, request: EventIngestRequest, correlation_id: str) -> EventIngestResponse:
        batch = EventBatchIngestRequest(events=[request])
        response = await self.ingest_batch(batch, correlation_id)
        item = response.results[0]
        if item.status == "rejected":
            from app.exceptions import ValidationError

            messages = "; ".join(e.message for e in item.errors)
            raise ValidationError(messages)

        return EventIngestResponse(
            event_id=item.event_id,  # type: ignore[arg-type]
            event_type=item.event_type or request.event_type,
            status="duplicate" if item.status == "duplicate" else "accepted",
            duplicate=item.status == "duplicate",
            duplicate_reason=item.duplicate_reason,
            correlation_id=item.correlation_id or correlation_id,
        )

    async def ingest_batch(
        self,
        batch: EventBatchIngestRequest,
        correlation_id: str,
    ) -> EventBatchIngestResponse:
        if hasattr(self._validator, "reset_cache"):
            self._validator.reset_cache()

        seen_event_ids: set[uuid.UUID] = set()
        seen_idempotency_keys: set[str] = set()

        client_event_ids = [e.event_id for e in batch.events if e.event_id is not None]
        existing_ids = await self._events.get_existing_ids(client_event_ids)

        results: list[EventIngestItemResult] = []
        accepted = duplicate = rejected = 0

        for index, request in enumerate(batch.events):
            result = await self._process_one(
                index=index,
                request=request,
                correlation_id=correlation_id,
                seen_event_ids=seen_event_ids,
                seen_idempotency_keys=seen_idempotency_keys,
                existing_ids=existing_ids,
            )
            results.append(result)
            if result.status == "accepted":
                accepted += 1
            elif result.status == "duplicate":
                duplicate += 1
            else:
                rejected += 1

        summary = BatchIngestSummary(
            total=len(batch.events),
            accepted=accepted,
            duplicate=duplicate,
            rejected=rejected,
        )

        logger.info(
            "event_batch_ingested",
            correlation_id=correlation_id,
            total=summary.total,
            accepted=summary.accepted,
            duplicate=summary.duplicate,
            rejected=summary.rejected,
        )

        if (
            self._metrics_projector is not None
            and self._settings.metrics_projector_enabled
            and (accepted > 0 or duplicate > 0)
        ):
            store_ids = {e.store_id for e in batch.events if e.store_id is not None}
            for store_id in store_ids:
                try:
                    await self._metrics_projector.project_footfall(
                        store_id,
                        hours_back=self._settings.metrics_projector_hours_back,
                    )
                except Exception as exc:
                    logger.warning(
                        "metrics_projection_failed",
                        store_id=str(store_id),
                        error=str(exc),
                    )

        return EventBatchIngestResponse(
            correlation_id=correlation_id,
            summary=summary,
            results=results,
        )

    async def _process_one(
        self,
        *,
        index: int,
        request: EventIngestRequest,
        correlation_id: str,
        seen_event_ids: set[uuid.UUID],
        seen_idempotency_keys: set[str],
        existing_ids: set[uuid.UUID],
    ) -> EventIngestItemResult:
        validation = await self._validator.validate(
            request,
            seen_event_ids=seen_event_ids,
            seen_idempotency_keys=seen_idempotency_keys,
        )
        if not validation.valid:
            return EventIngestItemResult(
                index=index,
                event_id=request.event_id,
                event_type=request.event_type,
                status="rejected",
                errors=validation.errors,
            )

        assert validation.store_id is not None
        assert validation.tenant_id is not None

        event_id = request.event_id or uuid.uuid4()
        if event_id in existing_ids:
            existing = await self._events.get_by_id(event_id)
            if existing is not None:
                return EventIngestItemResult(
                    index=index,
                    event_id=existing.id,
                    event_type=existing.event_type,
                    status="duplicate",
                    duplicate_reason=IngestOutcome.DUPLICATE_ID,
                    correlation_id=existing.correlation_id,
                )

        resolved_correlation = request.correlation_id or correlation_id
        payload = dict(request.payload)
        payload.setdefault("store_id", str(validation.store_id))

        session_id_raw = payload.get("session_id")
        session_id = uuid.UUID(str(session_id_raw)) if session_id_raw else None

        event = Event(
            id=event_id,
            store_id=validation.store_id,
            tenant_id=validation.tenant_id,
            session_id=session_id,
            event_type=request.event_type,
            schema_version=request.schema_version or self._settings.event_schema_version,
            aggregate_type=request.aggregate.type,
            aggregate_id=request.aggregate.id,
            payload=payload,
            correlation_id=resolved_correlation,
            causation_id=request.causation_id,
            idempotency_key=request.idempotency_key,
            occurred_at=request.occurred_at,
        )

        try:
            saved, outcome = await self._events.create_idempotent(event)
        except Exception as exc:
            logger.error(
                "event_ingest_failed",
                index=index,
                event_id=str(event_id),
                error=str(exc),
            )
            from app.schemas.events import IngestItemError

            return EventIngestItemResult(
                index=index,
                event_id=event_id,
                event_type=request.event_type,
                status="rejected",
                errors=[
                    IngestItemError(
                        code="persistence_error",
                        message="Failed to persist event",
                    )
                ],
            )

        if outcome == IngestOutcome.CREATED:
            existing_ids.add(saved.id)
            status = "accepted"
        else:
            status = "duplicate"

        return EventIngestItemResult(
            index=index,
            event_id=saved.id,
            event_type=saved.event_type,
            status=status,
            duplicate_reason=outcome if status == "duplicate" else None,
            correlation_id=saved.correlation_id,
        )
