"""Async cache abstraction.

Used by the patient summary endpoint (and the Celery rebuild task in Phase 3).
Cache failures degrade silently to "miss" — the cache is an optimisation,
not a source of truth.

The cache stores JSON-serialisable values. Non-JSON-native types (UUID, date,
datetime) are serialised via ``default=str``; callers parse them back through
their Pydantic schemas on read.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import redis.asyncio as redis_asyncio

from core.config import settings

log = logging.getLogger("medscribe.cache")


class CacheClient(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any) -> None: ...
    async def invalidate(self, key: str) -> None: ...


class RedisCache:
    """Thin async wrapper over ``redis.asyncio``. Connection is lazy."""

    def __init__(self, url: str) -> None:
        self._client = redis_asyncio.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001 — cache failure must never break a request
            log.warning("[cache] get failed for %s: %s", key, exc)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set(self, key: str, value: Any) -> None:
        try:
            await self._client.set(key, json.dumps(value, default=str))
        except Exception as exc:  # noqa: BLE001
            log.warning("[cache] set failed for %s: %s", key, exc)

    async def invalidate(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("[cache] invalidate failed for %s: %s", key, exc)

    async def close(self) -> None:
        await self._client.aclose()


class InMemoryCache:
    """Dict-backed cache used by tests (and as a safe default)."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str) -> Any | None:
        return self._store.get(key)

    async def set(self, key: str, value: Any) -> None:
        # Round-trip through JSON to surface non-serialisable values now,
        # matching the RedisCache behaviour exactly.
        self._store[key] = json.loads(json.dumps(value, default=str))

    async def invalidate(self, key: str) -> None:
        self._store.pop(key, None)


_cache: CacheClient | None = None


def get_cache() -> CacheClient:
    """FastAPI dependency. Singleton across requests."""
    global _cache
    if _cache is None:
        _cache = RedisCache(settings.REDIS_URL)
    return _cache


def patient_summary_key(patient_id: Any) -> str:
    return f"patient_summary:{patient_id}"
