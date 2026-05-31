from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Store, Tenant
from app.repositories.interfaces import StoreRepositoryProtocol


class StoreRepository(StoreRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, store_id: UUID) -> Store | None:
        stmt = select(Store).where(Store.id == store_id, Store.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_tenant_id_for_store(self, store_id: UUID) -> UUID | None:
        stmt = select(Store.tenant_id).where(Store.id == store_id, Store.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default_tenant(self, slug: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
