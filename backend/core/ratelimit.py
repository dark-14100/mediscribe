"""Application rate limiting (slowapi, Redis-backed).

Exposes a single shared ``Limiter`` so routes can apply per-endpoint limits with
a decorator. Counters live in Redis so limits hold across multiple worker
processes; under pytest the limiter is disabled and uses in-process memory so
the suite never touches the network or gets throttled.

Wire-up lives in ``main.py`` (``app.state.limiter`` + the 429 handler).
"""
import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from core.config import settings

log = logging.getLogger("medscribe.ratelimit")

# Rate limiting needs a live Redis and would only get in the way of the test
# suite, so turn it off there. Everywhere else (dev/prod) it is on.
_ENABLED = settings.ENVIRONMENT.strip().lower() != "test"

# Shared Redis counters in real deployments; harmless in-memory storage when
# disabled so importing this module never opens a socket during tests.
_STORAGE_URI = settings.REDIS_URL if _ENABLED else "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_STORAGE_URI,
    enabled=_ENABLED,
)
