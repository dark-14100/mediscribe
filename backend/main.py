"""FastAPI application factory.

This file owns: app construction, middleware, exception handlers, and router
registration. No business logic lives here.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import ResponseValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import analytics as analytics_routes
from api.routes import auth as auth_routes
from api.routes import notes as notes_routes
from api.routes import patients as patients_routes
from api.routes import pipeline as pipeline_routes
from api.routes import visits as visits_routes
from core.config import settings

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


def create_app() -> FastAPI:
    app = FastAPI(
        title="MedScribe AI",
        version="0.1.0",
        description="Intelligent medical documentation + longitudinal intelligence platform.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "medscribe-api"}

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
