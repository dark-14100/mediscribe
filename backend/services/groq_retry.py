"""Shared retry/backoff policy for Groq HTTP calls.

Every Groq-backed service (SOAP, transcription, compliance, bias, anomaly,
differential) routes its request through ``call_with_retries`` so a transient
failure — a timed-out connection, a dropped socket, or a 429/5xx from the
upstream API — is retried with exponential backoff instead of failing the
whole pipeline on the first hiccup. Deterministic failures (4xx other than
429, malformed-JSON ``ValueError``) are surfaced immediately; retrying them
would only waste the doctor's time.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

import httpx

from core.config import settings

log = logging.getLogger("medscribe.groq")

T = TypeVar("T")

# Status codes worth retrying: rate limiting + transient upstream errors.
_RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


async def call_with_retries(
    factory: Callable[[], Awaitable[T]],
    *,
    label: str,
    attempts: int | None = None,
    backoff: float | None = None,
) -> T:
    """Invoke ``factory`` (an async callable that performs one Groq request),
    retrying transient failures with exponential backoff.

    ``factory`` is re-invoked from scratch on each attempt, so it must build
    its own ``AsyncClient`` / request and raise on non-2xx (e.g. via
    ``response.raise_for_status()``) for retries to trigger.
    """
    max_attempts = (settings.GROQ_MAX_RETRIES if attempts is None else attempts) + 1
    base_backoff = (
        settings.GROQ_RETRY_BACKOFF_SECONDS if backoff is None else backoff
    )

    for attempt in range(1, max_attempts + 1):
        try:
            return await factory()
        except Exception as exc:  # noqa: BLE001 — re-raised below when non-retryable
            if attempt >= max_attempts or not _is_retryable(exc):
                raise
            delay = base_backoff * (2 ** (attempt - 1))
            log.warning(
                "[groq] %s attempt %d/%d failed (%s); retrying in %.2fs",
                label,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    # Unreachable: the loop either returns or raises.
    raise RuntimeError(f"call_with_retries exhausted for {label}")
