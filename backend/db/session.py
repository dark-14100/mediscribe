"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings

# SQLite's async driver uses a StaticPool that rejects pool_size/max_overflow,
# so only pass connection-pool args on real database backends.
_engine_kwargs: dict[str, Any] = {"echo": False}
if not settings.DATABASE_URL.startswith("sqlite"):
    # Supabase (and other PgBouncer transaction poolers) do not support asyncpg's
    # default prepared-statement cache — without this, requests 500 with
    # InvalidSQLStatementNameError after connections are recycled.
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={"statement_cache_size": 0},
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async session and rolls back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
