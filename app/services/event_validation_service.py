from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from app.repositories.interfaces import StoreRepositoryProtocol
from app.schemas.events import ALLOWED_EVENT_PREFIXES, EventIngestRequest, IngestItemError


@dataclass
class EventValidationResult:
    valid: bool
    errors: list[IngestItemError] = field(default_factory=list)
    store_id: UUID | None = None
    tenant_id: UUID | None = None


class EventValidationServiceProtocol(ABC):
    @abstractmethod
    async def validate(
        self,
        request: EventIngestRequest,
        *,
        seen_event_ids: set[UUID],
        seen_idempotency_keys: set[str],
    ) -> EventValidationResult: ...

    @abstractmethod
    def reset_cache(self) -> None: ...


class EventValidationService(EventValidationServiceProtocol):
    """Validates inbound events against business rules before persistence."""

    def __init__(self, store_repository: StoreRepositoryProtocol) -> None:
        self._stores = store_repository
        self._store_cache: dict[UUID, tuple[UUID, UUID]] = {}

    async def validate(
        self,
        request: EventIngestRequest,
        *,
        seen_event_ids: set[UUID],
        seen_idempotency_keys: set[str],
    ) -> EventValidationResult:
        errors: list[IngestItemError] = []

        if not any(request.event_type.startswith(p) for p in ALLOWED_EVENT_PREFIXES):
            errors.append(
                IngestItemError(
                    code="invalid_event_type",
                    message=f"event_type must start with one of {ALLOWED_EVENT_PREFIXES}",
                    field="event_type",
                )
            )

        if request.event_id is not None and request.event_id in seen_event_ids:
            errors.append(
                IngestItemError(
                    code="duplicate_event_id_in_batch",
                    message="event_id appears more than once in this batch",
                    field="event_id",
                )
            )

        if request.idempotency_key and request.idempotency_key in seen_idempotency_keys:
            errors.append(
                IngestItemError(
                    code="duplicate_idempotency_key_in_batch",
                    message="idempotency_key appears more than once in this batch",
                    field="idempotency_key",
                )
            )

        store_id: UUID | None = None
        tenant_id: UUID | None = None

        try:
            store_id = self._extract_store_id(request)
        except ValueError as exc:
            errors.append(
                IngestItemError(
                    code="invalid_store_id",
                    message=str(exc),
                    field="store_id",
                )
            )

        if store_id is not None and not errors:
            tenant_id = await self._resolve_tenant(store_id, request.tenant_id, errors)

        if not errors:
            if request.event_id is not None:
                seen_event_ids.add(request.event_id)
            if request.idempotency_key:
                seen_idempotency_keys.add(request.idempotency_key)

        return EventValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            store_id=store_id if not errors else None,
            tenant_id=tenant_id if not errors else None,
        )

    async def _resolve_tenant(
        self,
        store_id: UUID,
        requested_tenant_id: UUID | None,
        errors: list[IngestItemError],
    ) -> UUID | None:
        if store_id in self._store_cache:
            cached_tenant, _ = self._store_cache[store_id]
            if requested_tenant_id is not None and requested_tenant_id != cached_tenant:
                errors.append(
                    IngestItemError(
                        code="tenant_store_mismatch",
                        message="tenant_id does not match store tenant",
                        field="tenant_id",
                    )
                )
                return None
            return cached_tenant

        store = await self._stores.get_by_id(store_id)
        if store is None:
            errors.append(
                IngestItemError(
                    code="store_not_found",
                    message=f"store not found: {store_id}",
                    field="store_id",
                )
            )
            return None

        if requested_tenant_id is not None and requested_tenant_id != store.tenant_id:
            errors.append(
                IngestItemError(
                    code="tenant_store_mismatch",
                    message="tenant_id does not match store tenant",
                    field="tenant_id",
                )
            )
            return None

        tenant_id = requested_tenant_id or store.tenant_id
        self._store_cache[store_id] = (tenant_id, store_id)
        return tenant_id

    def _extract_store_id(self, request: EventIngestRequest) -> UUID:
        if request.store_id is not None:
            return request.store_id
        raw = request.payload.get("store_id")
        if raw is None:
            raise ValueError("store_id is required on the request or in payload")
        return UUID(str(raw))

    def reset_cache(self) -> None:
        self._store_cache.clear()
