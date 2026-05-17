"""Pytest fixtures: test env, async SQLite engine, DB session, and ASGI client.

SQLite is used as the test database (per Phase 1 decision). pgvector / ARRAY /
JSONB columns are PostgreSQL-only, so for Phase 1 we create ONLY the User
table (the only one auth touches) directly from its ORM metadata. Tests for
later phases that need other tables will gain their own DB setup.
"""
import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

# --- Path + env setup MUST happen before app imports ---
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Force-set test env BEFORE any app module reads settings — overrides whatever
# leaked in from the shell or a developer's local .env file.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-not-for-production-do-not-use"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-do-not-use"
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.security import create_access_token, hash_password  # noqa: E402
from db.base import Base  # noqa: E402
from db.session import get_db  # noqa: E402
from main import app  # noqa: E402
from models import Patient, User, Visit  # noqa: E402
from services.cache import InMemoryCache, get_cache  # noqa: E402
from workers.celery_app import celery_app  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_celery_send_task(monkeypatch):
    """Celery's send_task tries to reach Redis on first use. Stub it in every
    test so route code that fires off background tasks doesn't block on a
    non-existent broker."""

    def _noop_send_task(name, args=None, kwargs=None, **opts):
        return None

    monkeypatch.setattr(celery_app, "send_task", _noop_send_task)

# visit_embeddings uses pgvector which has no SQLite implementation, so we
# explicitly limit table creation to the three structured tables.
_TEST_TABLES = ("users", "patients", "visits")


@pytest_asyncio.fixture
async def db_engine():
    """Fresh in-memory SQLite engine per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c,
                tables=[Base.metadata.tables[name] for name in _TEST_TABLES],
            )
        )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    sessionmaker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def fake_cache() -> InMemoryCache:
    return InMemoryCache()


@pytest_asyncio.fixture
async def client(db_session, fake_cache) -> AsyncGenerator[AsyncClient, None]:
    """ASGI client with get_db + get_cache overridden to use test fixtures."""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _override_get_cache() -> InMemoryCache:
        return fake_cache

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_cache] = _override_get_cache
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --- Convenience factories for tests that need authenticated users ---


@pytest_asyncio.fixture
async def doctor_user(db_session) -> User:
    user = User(
        email="doctor@test.local",
        hashed_password=hash_password("password123"),
        full_name="Dr. Alice",
        role="doctor",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    user = User(
        email="admin@test.local",
        hashed_password=hash_password("password123"),
        full_name="Admin Bob",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def second_doctor(db_session) -> User:
    user = User(
        email="other@test.local",
        hashed_password=hash_password("password123"),
        full_name="Dr. Other",
        role="doctor",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id), role=user.role)
    return {"Authorization": f"Bearer {token}"}


__all__ = [
    "auth_header",
    "Patient",
    "Visit",
]
