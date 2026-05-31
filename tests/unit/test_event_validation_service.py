# PROMPT:
# Generate complete pytest suite — EventValidationService business rule unit tests.
#
# CHANGES MADE:
# - Rejects invalid types, unknown stores, tenant mismatch, and duplicate event_id in batch.

import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.events import EventAggregate, EventIngestRequest
from app.services.event_validation_service import EventValidationService


class InMemoryStoreRepo:
    """Minimal store repo for validation unit tests — no mocks, real logic paths."""

    def __init__(self, store_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.store_id = store_id
        self.tenant_id = tenant_id

    async def get_by_id(self, store_id: uuid.UUID):
        if store_id == self.store_id:
            return type("Store", (), {"id": store_id, "tenant_id": self.tenant_id})()
        return None

    async def get_tenant_id_for_store(self, store_id: uuid.UUID):
        if store_id == self.store_id:
            return self.tenant_id
        return None

    async def get_default_tenant(self, slug: str):
        return None


def _valid_request(
    store_id: uuid.UUID,
    *,
    event_id: uuid.UUID | None = None,
    event_type: str = "vision.frame.processed",
    idempotency_key: str | None = None,
) -> EventIngestRequest:
    return EventIngestRequest(
        event_id=event_id,
        event_type=event_type,
        occurred_at=datetime.now(tz=UTC),
        store_id=store_id,
        idempotency_key=idempotency_key,
        aggregate=EventAggregate(type="pipeline_run", id=uuid.uuid4()),
        payload={"frame_index": 1},
    )


@pytest.mark.asyncio
async def test_validation_rejects_invalid_event_type() -> None:
    store_id = uuid.uuid4()
    svc = EventValidationService(InMemoryStoreRepo(store_id, uuid.uuid4()))
    result = await svc.validate(
        _valid_request(store_id, event_type="invalid.event"),
        seen_event_ids=set(),
        seen_idempotency_keys=set(),
    )
    assert not result.valid
    assert result.errors[0].code == "invalid_event_type"


@pytest.mark.asyncio
async def test_validation_rejects_missing_store_id() -> None:
    svc = EventValidationService(InMemoryStoreRepo(uuid.uuid4(), uuid.uuid4()))
    request = EventIngestRequest(
        event_type="vision.frame.processed",
        occurred_at=datetime.now(tz=UTC),
        aggregate=EventAggregate(type="track", id=uuid.uuid4()),
        payload={},
    )
    result = await svc.validate(request, seen_event_ids=set(), seen_idempotency_keys=set())
    assert not result.valid
    assert any(e.code == "invalid_store_id" for e in result.errors)


@pytest.mark.asyncio
async def test_validation_rejects_duplicate_event_id_in_batch() -> None:
    store_id = uuid.uuid4()
    svc = EventValidationService(InMemoryStoreRepo(store_id, uuid.uuid4()))
    event_id = uuid.uuid4()
    seen: set[uuid.UUID] = set()

    first = await svc.validate(
        _valid_request(store_id, event_id=event_id),
        seen_event_ids=seen,
        seen_idempotency_keys=set(),
    )
    assert first.valid

    second = await svc.validate(
        _valid_request(store_id, event_id=event_id),
        seen_event_ids=seen,
        seen_idempotency_keys=set(),
    )
    assert not second.valid
    assert second.errors[0].code == "duplicate_event_id_in_batch"


@pytest.mark.asyncio
async def test_validation_rejects_unknown_store() -> None:
    store_id = uuid.uuid4()
    svc = EventValidationService(InMemoryStoreRepo(uuid.uuid4(), uuid.uuid4()))
    result = await svc.validate(
        _valid_request(store_id),
        seen_event_ids=set(),
        seen_idempotency_keys=set(),
    )
    assert not result.valid
    assert result.errors[0].code == "store_not_found"


@pytest.mark.asyncio
async def test_validation_rejects_tenant_store_mismatch() -> None:
    store_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    wrong_tenant = uuid.uuid4()
    svc = EventValidationService(InMemoryStoreRepo(store_id, tenant_id))
    request = _valid_request(store_id)
    request = request.model_copy(update={"tenant_id": wrong_tenant})
    result = await svc.validate(request, seen_event_ids=set(), seen_idempotency_keys=set())
    assert not result.valid
    assert result.errors[0].code == "tenant_store_mismatch"


@pytest.mark.asyncio
async def test_validation_accepts_valid_event() -> None:
    store_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    svc = EventValidationService(InMemoryStoreRepo(store_id, tenant_id))
    result = await svc.validate(
        _valid_request(store_id),
        seen_event_ids=set(),
        seen_idempotency_keys=set(),
    )
    assert result.valid
    assert result.store_id == store_id
    assert result.tenant_id == tenant_id
