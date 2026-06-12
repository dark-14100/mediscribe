"""Rate-limit guard tests.

The limiter is disabled in the test environment (so the rest of the suite isn't
throttled), so here we temporarily flip it on and assert that exceeding the auth
limit yields HTTP 429.
"""
import pytest

from core.config import settings
from core.ratelimit import limiter


@pytest.mark.asyncio
async def test_login_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)
    # Reset any counters carried over so the threshold is deterministic.
    limiter.reset()

    # RATE_LIMIT_AUTH defaults to "5/minute": the first 5 attempts hit the
    # endpoint (401 invalid creds), the 6th is blocked by the limiter.
    allowed = int(settings.RATE_LIMIT_AUTH.split("/")[0])
    body = {"email": "nobody@example.com", "password": "wrong-password"}

    statuses = []
    for _ in range(allowed + 1):
        resp = await client.post("/auth/login", json=body)
        statuses.append(resp.status_code)

    assert statuses[-1] == 429
    assert all(code != 429 for code in statuses[:-1])

    limiter.reset()
