from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.repositories.crud.base import CRUDRepository
from app.repositories.interfaces import TransactionRepositoryProtocol


class TransactionRepository(CRUDRepository[Transaction], TransactionRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Transaction)

    async def create_idempotent(self, transaction: Transaction) -> tuple[Transaction, bool]:
        if transaction.external_ref:
            existing = await self.get_by_external_ref(
                transaction.store_id, transaction.external_ref
            )
            if existing is not None:
                return existing, True

        try:
            async with self._session.begin_nested():
                saved = await self.create(transaction)
            return saved, False
        except IntegrityError:
            if transaction.external_ref:
                existing = await self.get_by_external_ref(
                    transaction.store_id, transaction.external_ref
                )
                if existing is not None:
                    return existing, True
            raise

    async def get_by_external_ref(self, store_id: UUID, external_ref: str) -> Transaction | None:
        stmt = select(Transaction).where(
            Transaction.store_id == store_id,
            Transaction.external_ref == external_ref,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_store(
        self,
        store_id: UUID,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Transaction]:
        stmt = (
            select(Transaction)
            .where(Transaction.store_id == store_id)
            .order_by(Transaction.occurred_at.desc())
            .offset(offset)
            .limit(min(limit, 500))
        )
        if from_ts is not None:
            stmt = stmt.where(Transaction.occurred_at >= from_ts)
        if to_ts is not None:
            stmt = stmt.where(Transaction.occurred_at <= to_ts)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
