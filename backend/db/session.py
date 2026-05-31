"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.config import settings


def _uses_pgbouncer(url: str) -> bool:
    """Supabase/Railway pooler URLs must not use asyncpg prepared statement caches."""
    lower = url.lower()
    return (
        "pooler" in lower
        or "pgbouncer" in lower
        or ":6543/" in lower
        or ":6543?" in lower
    )


def _engine_url(url: str) -> str:
    """SQLAlchemy asyncpg dialect also reads prepared_statement_cache_size from the URL."""
    if not _uses_pgbouncer(url):
        return url
    if "prepared_statement_cache_size" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}prepared_statement_cache_size=0"


def _pgbouncer_connect_args() -> dict[str, Any]:
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


_engine_kwargs: dict[str, Any] = {"echo": False}
_db_url = _engine_url(settings.DATABASE_URL)

if settings.DATABASE_URL.startswith("sqlite"):
    pass
elif _uses_pgbouncer(settings.DATABASE_URL):
    # Let PgBouncer own pooling; avoid SQLAlchemy pool + prepared statements.
    _engine_kwargs.update(
        poolclass=NullPool,
        connect_args=_pgbouncer_connect_args(),
    )
else:
    _engine_kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=10)

engine = create_async_engine(_db_url, **_engine_kwargs)

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
