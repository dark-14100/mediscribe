"""FastAPI application factory.

This file owns: app construction, middleware, exception handlers, and router
registration. No business logic lives here.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import ResponseValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.routes import analytics as analytics_routes
from api.routes import auth as auth_routes
from api.routes import notes as notes_routes
from api.routes import patients as patients_routes
from api.routes import pipeline as pipeline_routes
from api.routes import visits as visits_routes
from core.config import settings
from core.ratelimit import limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("medscribe")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("[main] MedScribe API starting (debug=%s)", False)
    yield
    log.info("[main] MedScribe API shutting down")


def _validate_production_secrets() -> None:
    """Fail fast if production is running with a weak/placeholder JWT secret."""
    if not settings.is_production:
        return
    secret = settings.JWT_SECRET_KEY or ""
    weak_markers = ("change_me", "test-secret", "secret", "changeme")
    if len(secret) < 32 or any(marker in secret.lower() for marker in weak_markers):
        raise RuntimeError(
            "JWT_SECRET_KEY is missing, too short, or a placeholder. "
            "Set a strong (>=32 char) random secret in production."
        )


def _validate_production_transport() -> None:
    """Refuse plaintext Redis in production — the broker/cache carries PHI-derived
    data (cached summaries, task args) and must be encrypted in transit (rediss://).

    Local addresses are exempted so a single-host deployment talking to a
    co-located Redis over loopback isn't forced onto TLS.
    """
    if not settings.is_production:
        return
    url = (settings.REDIS_URL or "").strip().lower()
    is_local = "localhost" in url or "127.0.0.1" in url or "@redis:" in url
    if url.startswith("redis://") and not is_local:
        raise RuntimeError(
            "REDIS_URL must use TLS (rediss://) in production to protect "
            "PHI-derived data in transit."
        )


def create_app() -> FastAPI:
    _validate_production_secrets()
    _validate_production_transport()

    # Hide interactive API docs / schema in production to reduce attack surface.
    docs_kwargs: dict[str, str | None] = {}
    if settings.is_production:
        docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

    app = FastAPI(
        title="MedScribe AI",
        version="0.1.0",
        description="Intelligent medical documentation + longitudinal intelligence platform.",
        lifespan=lifespan,
        **docs_kwargs,
    )

    # Rate limiting: slowapi reads the limiter off app.state and converts a
    # breach into a 429 via its handler.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["meta"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "medscribe-api",
            "commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "local")[:12],
        }

    @app.exception_handler(ResponseValidationError)
    async def response_validation_handler(
        _: Request, exc: ResponseValidationError
    ) -> JSONResponse:
        log.exception("[main] response validation failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        log.exception("[main] unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    app.include_router(auth_routes.router)
    app.include_router(patients_routes.router)
    app.include_router(visits_routes.router)
    app.include_router(pipeline_routes.router)
    app.include_router(notes_routes.router)
    app.include_router(analytics_routes.router)

    return app


app = create_app()
