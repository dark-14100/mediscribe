"""Embedding service — sentence-transformers + Celery task for RAG ingestion.

Responsibilities:
* Provide a process-level singleton of the all-MiniLM-L6-v2 model so the
  model is loaded once and reused across all calls.
* Expose ``embed_text`` for synchronous embedding of any string.
* Expose the ``embed_visit`` Celery task that runs after a note is saved:
  it reads the visit's SOAP note + raw transcript, produces two 384-dim
  vectors, and upserts them into the visit_embeddings table.

The Celery task is registered under the name ``workers.tasks.embed_visit``
so that the backend's ``_queue_embed_visit`` helper (in notes.py) can send
it without importing this module directly.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config import settings
from db.session import AsyncSessionLocal
from models.embedding import VisitEmbedding
from models.visit import Visit
from workers.celery_app import celery_app

log = logging.getLogger("medscribe.embedding")

# ---------------------------------------------------------------------------
# Singleton model loader
# ---------------------------------------------------------------------------

_model = None


def _get_model():
    global _model  # noqa: PLW0603
    if _model is None:
        from sentence_transformers import SentenceTransformer  # lazy: avoids torch DLL load at import time
        log.info("[embedding] loading model %s", settings.EMBEDDING_MODEL)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        log.info("[embedding] model loaded")
    return _model


# ---------------------------------------------------------------------------
# Public embedding helper
# ---------------------------------------------------------------------------


def embed_text(text: str) -> list[float]:
    """Return a 384-dim embedding vector for *text*.

    Runs on CPU, no GPU required. The model is loaded once per process and
    reused for all subsequent calls.
    """
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


# ---------------------------------------------------------------------------
# Async DB helpers (called via asyncio.run inside the Celery task)
# ---------------------------------------------------------------------------


def _soap_to_text(soap_note: dict) -> str:
    """Concatenate all four SOAP field texts into a single string for embedding."""
    parts = []
    for field in ("subjective", "objective", "assessment", "plan"):
        field_data = soap_note.get(field, {})
        if isinstance(field_data, dict):
            text = field_data.get("text", "")
        else:
            text = str(field_data)
        if text:
            parts.append(text)
    return " ".join(parts)


def _extract_patient_speech(raw_transcript: str) -> str:
    """Extract patient-labelled lines from the stored raw transcript string.

    The raw transcript is stored as newline-separated lines in the format:
        [doctor] text here
        [patient] text here
    """
    patient_lines = []
    for line in raw_transcript.splitlines():
        if line.startswith("[patient]"):
            patient_lines.append(line[len("[patient]"):].strip())
    return " ".join(patient_lines)


async def _embed_and_store(visit_id: str) -> None:
    """Core async logic: load visit, generate embeddings, upsert into DB."""
    async with AsyncSessionLocal() as session:
        visit: Visit | None = await session.scalar(
            select(Visit).where(Visit.id == UUID(visit_id))
        )
        if visit is None:
            log.warning("[embedding] visit not found visit_id=%s — skipping", visit_id)
            return

        soap_note: dict = visit.soap_note or {}
        raw_transcript: str = visit.raw_transcript or ""

        # --- Full SOAP note embedding (used for RAG history retrieval) ---
        soap_text = _soap_to_text(soap_note)
        if not soap_text.strip():
            log.warning(
                "[embedding] visit %s has empty SOAP note — embedding empty string",
                visit_id,
            )
        full_note_vector = embed_text(soap_text) if soap_text.strip() else embed_text(" ")

        # --- Patient-speech-only embedding (used for drift detection) ---
        patient_speech = _extract_patient_speech(raw_transcript)
        patient_speech_vector: list[float] | None = (
            embed_text(patient_speech) if patient_speech.strip() else None
        )

        # Upsert: if a row already exists for this visit (re-save after edit), update it.
        stmt = (
            pg_insert(VisitEmbedding)
            .values(
                visit_id=UUID(visit_id),
                patient_id=visit.patient_id,
                full_note_embedding=full_note_vector,
                patient_speech_embedding=patient_speech_vector,
            )
            .on_conflict_do_update(
                index_elements=["visit_id"],
                set_={
                    "full_note_embedding": full_note_vector,
                    "patient_speech_embedding": patient_speech_vector,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()

    log.info(
        "[embedding] stored embeddings visit_id=%s patient_speech_present=%s",
        visit_id,
        patient_speech_vector is not None,
    )


# ---------------------------------------------------------------------------
# Celery task — registered as "workers.tasks.embed_visit" so the backend's
# _queue_embed_visit call in notes.py finds it without importing this module.
# ---------------------------------------------------------------------------


@celery_app.task(
    name="workers.tasks.embed_visit",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def embed_visit(self, visit_id: str) -> None:  # noqa: ARG001
    """Generate and store SOAP + patient-speech embeddings for a saved visit."""
    asyncio.run(_embed_and_store(visit_id))
