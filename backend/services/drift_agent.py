"""Linguistic drift detection agent — pipeline Step 4c.

Compares the patient's current speech embedding against prior visit embeddings
stored in visit_embeddings.patient_speech_embedding. Returns None when there
is insufficient history (< 2 prior embeddings).

The pipeline route calls this as:
    from services.drift_agent import detect
    drift_flag = await detect(patient_id, transcript)
"""
from __future__ import annotations

import logging
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.constants import NEGATIVE_AFFECT_KEYWORDS, PAIN_KEYWORDS
from db.session import AsyncSessionLocal
from models.embedding import VisitEmbedding
from models.visit import Visit
from schemas.pipeline import DriftDirection, DriftFlag, TranscriptLine
from services.embedding import embed_text

log = logging.getLogger("medscribe.drift_agent")

_MIN_HISTORY = 2   # minimum prior patient-speech embeddings required
_HISTORY_LIMIT = 3  # how many past visits to compare against


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_patient_speech(transcript: list[TranscriptLine]) -> str:
    return " ".join(t.text for t in transcript if t.speaker == "patient")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Dot product of two L2-normalised unit vectors equals cosine similarity."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    return float(np.dot(va, vb))


def _determine_direction(patient_text: str) -> DriftDirection:
    text_lower = patient_text.lower()
    pain_count = sum(1 for kw in PAIN_KEYWORDS if kw in text_lower)
    neg_count = sum(1 for kw in NEGATIVE_AFFECT_KEYWORDS if kw in text_lower)
    if pain_count > 0 and pain_count >= neg_count:
        return "increased_pain_descriptors"
    if neg_count > 0:
        return "increased_negative_affect"
    # Drift was detected but no dominant keyword cluster — default to the
    # more clinically conservative label.
    return "increased_negative_affect"


async def _fetch_prior_speech_embeddings(
    patient_id: UUID,
    session: AsyncSession,
) -> list[list[float]]:
    """Return up to _HISTORY_LIMIT patient_speech_embedding vectors, newest first."""
    result = await session.execute(
        select(VisitEmbedding.patient_speech_embedding)
        .join(Visit, VisitEmbedding.visit_id == Visit.id)
        .where(
            VisitEmbedding.patient_id == patient_id,
            VisitEmbedding.patient_speech_embedding.isnot(None),
        )
        .order_by(Visit.visit_date.desc())
        .limit(_HISTORY_LIMIT)
    )
    return [list(row[0]) for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def detect(
    patient_id: UUID,
    transcript: list[TranscriptLine],
    db: AsyncSession | None = None,
) -> DriftFlag | None:
    """Detect linguistic drift in patient speech compared to prior visits.

    Returns None when:
    - The transcript has no patient speech lines.
    - Fewer than 2 prior patient-speech embeddings exist in the DB.

    The optional ``db`` parameter is accepted so unit tests can inject a mock
    session directly and skip the AsyncSessionLocal context manager.
    """
    patient_text = _extract_patient_speech(transcript)
    if not patient_text.strip():
        log.info("[drift_agent] no patient speech in transcript — skipping")
        return None

    current_vector = embed_text(patient_text)

    if db is not None:
        prior_vectors = await _fetch_prior_speech_embeddings(patient_id, db)
    else:
        async with AsyncSessionLocal() as _db:
            prior_vectors = await _fetch_prior_speech_embeddings(patient_id, _db)

    if len(prior_vectors) < _MIN_HISTORY:
        log.info(
            "[drift_agent] only %d prior embedding(s) for patient %s — insufficient history",
            len(prior_vectors),
            patient_id,
        )
        return None

    similarities = [_cosine_similarity(current_vector, pv) for pv in prior_vectors]
    drift_score = 1.0 - float(np.mean(similarities))
    flagged = drift_score > settings.DRIFT_THRESHOLD

    direction: DriftDirection = (
        _determine_direction(patient_text) if flagged else "no_significant_drift"
    )

    log.info(
        "[drift_agent] drift_score=%.4f threshold=%.4f flagged=%s direction=%s",
        drift_score,
        settings.DRIFT_THRESHOLD,
        flagged,
        direction,
    )

    return DriftFlag(
        flagged=flagged,
        direction=direction,
        delta=round(drift_score, 6),
        threshold=settings.DRIFT_THRESHOLD,
    )
