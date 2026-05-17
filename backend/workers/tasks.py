"""Celery tasks.

These tasks run in a separate worker process from FastAPI. Celery itself is
synchronous, so async code is bridged via ``asyncio.run`` inside the task body.

Tasks owned by backend (this file):
* ``invalidate_patient_summary`` — drops the Redis summary cache for a patient
  (called after a note is saved or signed so the next GET rebuilds fresh).
* ``upload_audio_to_b2`` — uploads a raw audio blob to Backblaze B2 and writes
  the returned object URL onto ``visits.audio_url``.

Tasks owned by the AI team (NOT in this file):
* ``embed_visit`` — generates and stores SOAP-note + patient-speech embeddings.
  Will be added by whoever owns ``services/embedding.py``.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from uuid import UUID

from sqlalchemy import update

from core.config import settings
from db.session import AsyncSessionLocal
from models.visit import Visit
from services.cache import RedisCache, patient_summary_key
from services.storage import B2Storage, InMemoryStorage, StorageClient
from workers.celery_app import celery_app

log = logging.getLogger("medscribe.tasks")


# --- Internal async helpers (kept private; Celery tasks below call them via asyncio.run) ---


async def _invalidate_patient_summary_async(patient_id: str) -> None:
    cache = RedisCache(settings.REDIS_URL)
    try:
        await cache.invalidate(patient_summary_key(patient_id))
        log.info("[tasks] invalidated patient_summary patient_id=%s", patient_id)
    finally:
        await cache.close()


def _build_storage_for_worker() -> StorageClient:
    """Workers init their own storage client (separate process from the API)."""
    try:
        return B2Storage(
            key_id=settings.BACKBLAZE_KEY_ID,
            app_key=settings.BACKBLAZE_APP_KEY,
            bucket_name=settings.BACKBLAZE_BUCKET,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "[tasks] worker B2 init failed (%s) — using in-memory storage fallback", exc
        )
        return InMemoryStorage()


async def _upload_audio_async(
    visit_id: str,
    audio_b64: str,
    content_type: str,
) -> str:
    audio_bytes = base64.b64decode(audio_b64)
    storage = _build_storage_for_worker()
    url = await storage.upload_audio(audio_bytes, visit_id, content_type)

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Visit).where(Visit.id == UUID(visit_id)).values(audio_url=url)
        )
        await session.commit()
    log.info("[tasks] uploaded audio visit_id=%s url=%s", visit_id, url)
    return url


# --- Celery task definitions ---


@celery_app.task(name="workers.tasks.invalidate_patient_summary")
def invalidate_patient_summary(patient_id: str) -> None:
    """Drop the cached patient summary so the next /summary call rebuilds it."""
    asyncio.run(_invalidate_patient_summary_async(patient_id))


@celery_app.task(
    name="workers.tasks.upload_audio_to_b2",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def upload_audio_to_b2(
    self,  # noqa: ARG001 — Celery passes the task instance when bind=True
    visit_id: str,
    audio_b64: str,
    content_type: str = "audio/webm",
) -> str:
    """Upload base64-encoded audio bytes to B2 and persist the URL on the visit row."""
    return asyncio.run(_upload_audio_async(visit_id, audio_b64, content_type))
