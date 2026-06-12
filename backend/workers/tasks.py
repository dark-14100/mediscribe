"""Celery tasks.

These tasks run in a separate worker process from FastAPI. Celery itself is
synchronous, so async code is bridged via ``asyncio.run`` inside the task body.

Tasks owned by backend (this file):
* ``invalidate_patient_summary`` — drops the Redis summary cache for a patient
  (called after a note is saved or signed so the next GET rebuilds fresh).

Audio is intentionally NOT uploaded via Celery: routing raw audio (PHI) through
the Redis broker would leave it base64-encoded in an unencrypted queue. The
transcribe route archives audio to object storage in-process instead.

Tasks owned by the AI team (NOT in this file):
* ``embed_visit`` — generates and stores SOAP-note + patient-speech embeddings.
  Will be added by whoever owns ``services/embedding.py``.
"""
from __future__ import annotations

import asyncio
import logging

from core.config import settings
from services.cache import RedisCache, patient_summary_key
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


# --- Celery task definitions ---


@celery_app.task(name="workers.tasks.invalidate_patient_summary")
def invalidate_patient_summary(patient_id: str) -> None:
    """Drop the cached patient summary so the next /summary call rebuilds it."""
    asyncio.run(_invalidate_patient_summary_async(patient_id))
