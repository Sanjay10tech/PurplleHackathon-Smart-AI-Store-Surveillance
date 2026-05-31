from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


class CRUDRepository(Generic[ModelT]):
    """Generic async CRUD operations for SQLAlchemy ORM models."""

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self._session = session
        self._model = model

    async def get_by_id(self, entity_id: UUID) -> ModelT | None:
        return await self._session.get(self._model, entity_id)

    async def create(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def update(self, entity: ModelT) -> ModelT:
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self._session.delete(entity)
        await self._session.flush()

    async def delete_by_id(self, entity_id: UUID) -> bool:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            return False
        await self.delete(entity)
        return True

    async def list_all(self, *, offset: int = 0, limit: int = 100) -> list[ModelT]:
        stmt = select(self._model).offset(offset).limit(min(limit, 500))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
