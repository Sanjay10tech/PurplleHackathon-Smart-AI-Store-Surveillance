from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings, get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create or return the singleton async database engine."""
    global _engine
    if _engine is not None:
        return _engine

    cfg = settings or get_settings()
    engine_kwargs: dict = {
        "echo": cfg.environment == "development" and cfg.log_level.upper() == "DEBUG",
    }
    if cfg.database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_size"] = cfg.db_pool_size
        engine_kwargs["max_overflow"] = cfg.db_max_overflow
        engine_kwargs["pool_pre_ping"] = cfg.db_pool_pre_ping

    _engine = create_async_engine(cfg.database_url, **engine_kwargs)
    return _engine


def create_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Create or return the singleton session factory."""
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    _session_factory = async_sessionmaker(
        bind=engine or create_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a transactional database session."""
    session_factory = create_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_database_connection() -> bool:
    """Return True if the database accepts connections."""
    from sqlalchemy import text

    engine = create_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose_engine() -> None:
    """Dispose engine on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_engine_singleton() -> None:
    """Reset singleton engine state (used in tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
