import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database import (
    Base,
    create_engine,
    create_session_factory,
    dispose_engine,
    reset_engine_singleton,
)
from app.dependencies import get_db_session
from app.main import create_app
from app.models import Store, Tenant
from app.repositories.anomaly_repository import AnomalyRepository
from app.repositories.event_repository import EventRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.heatmap_repository import HeatmapRepository
from app.repositories.store_metric_repository import StoreMetricRepository
from app.repositories.store_repository import StoreRepository
from app.services.analytics_service import AnalyticsService
from app.services.anomaly_service import AnomalyService
from app.services.event_ingestion_service import EventIngestionService
from app.services.event_validation_service import EventValidationService
from app.services.funnel_service import FunnelService
from app.services.heatmap_service import HeatmapService
from tests.helpers.constants import DEMO_STORE_ID, DEMO_TENANT_ID

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session_factory() -> AsyncGenerator:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["API_KEY_REQUIRED"] = "false"
    get_settings.cache_clear()
    reset_engine_singleton()

    engine = create_engine()
    session_factory = create_session_factory(engine)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield session_factory

    await dispose_engine()
    reset_engine_singleton()
    get_settings.cache_clear()


@pytest.fixture
async def seeded_store(db_session_factory) -> uuid.UUID:
    store_id = DEMO_STORE_ID
    async with db_session_factory() as session:
        tenant = Tenant(
            id=DEMO_TENANT_ID,
            name="Test Tenant",
            slug="default",
        )
        session.add(tenant)
        session.add(
            Store(
                id=store_id,
                tenant_id=tenant.id,
                name="Test Store",
                timezone="UTC",
                config={"heatmap": {"use_layout": False}},
            )
        )
        await session.commit()
    return store_id


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return DEMO_TENANT_ID


@pytest.fixture
async def funnel_service(db_session_factory):
    async with db_session_factory() as session:
        yield FunnelService(
            funnel_repository=FunnelRepository(session),
            store_repository=StoreRepository(session),
            event_repository=EventRepository(session),
        ), session


@pytest.fixture
async def heatmap_service(db_session_factory):
    async with db_session_factory() as session:
        yield HeatmapService(
            heatmap_repository=HeatmapRepository(session),
            store_repository=StoreRepository(session),
        ), session


@pytest.fixture
async def anomaly_service(db_session_factory):
    async with db_session_factory() as session:
        yield AnomalyService(
            heatmap_repository=HeatmapRepository(session),
            funnel_repository=FunnelRepository(session),
            store_repository=StoreRepository(session),
            anomaly_repository=AnomalyRepository(session),
            event_repository=EventRepository(session),
        ), session


@pytest.fixture
async def ingestion_service(db_session_factory):
    async with db_session_factory() as session:
        yield EventIngestionService(
            event_repository=EventRepository(session),
            validation_service=EventValidationService(StoreRepository(session)),
            settings=get_settings(),
            metrics_projector=__import__(
                "app.services.metrics_projector_service",
                fromlist=["MetricsProjectorService"],
            ).MetricsProjectorService(session),
        ), session


@pytest.fixture
async def analytics_service(db_session_factory):
    async with db_session_factory() as session:
        yield AnalyticsService(
            metric_repository=StoreMetricRepository(session),
            store_repository=StoreRepository(session),
            event_repository=EventRepository(session),
            anomaly_repository=AnomalyRepository(session),
        ), session


@pytest.fixture
async def client(db_session_factory) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    async def override_get_db() -> AsyncGenerator:
        async with db_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def mock_db_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.database.check_database_connection",
        AsyncMock(return_value=True),
    )
