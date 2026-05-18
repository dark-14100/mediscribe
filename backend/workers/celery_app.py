"""Celery application — broker and result backend both on Redis (Upstash).

Tasks themselves live in ``workers.tasks`` (filled in during Phase 3).
The worker is started via:

    celery -A workers.celery_app worker --loglevel=info
"""
from celery import Celery

from core.config import settings

celery_app = Celery(
    "medscribe",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # services.embedding registers "workers.tasks.embed_visit" under the
    # same task name expected by notes.py — both modules must be included.
    include=["workers.tasks", "services.embedding"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_default_queue="default",
    broker_connection_retry_on_startup=True,
    # Hackathon-scale: don't prefetch huge batches.
    worker_prefetch_multiplier=1,
)
