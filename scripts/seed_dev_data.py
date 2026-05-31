"""Seed a demo store for local development and Docker first boot."""

import asyncio
import uuid

from sqlalchemy import select

from app.database import create_engine, create_session_factory
from app.models import Store, Tenant


async def seed() -> None:
    engine = create_engine()
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "default"))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                name="Default Tenant",
                slug="default",
            )
            session.add(tenant)
            await session.flush()

        store_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
        existing = (
            await session.execute(select(Store).where(Store.id == store_id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Store(
                    id=store_id,
                    tenant_id=tenant.id,
                    name="Demo Store",
                    timezone="UTC",
                    config={"pipeline_profile": "default"},
                )
            )

        await session.commit()
        print(f"Seeded demo store: {store_id}")


if __name__ == "__main__":
    asyncio.run(seed())
