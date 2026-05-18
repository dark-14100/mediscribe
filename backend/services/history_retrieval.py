"""History retrieval service — RAG pipeline Step 3.

Retrieves the top-5 semantically relevant past visits for a patient using
pgvector cosine similarity, then summarises each into a compact 3-line string
safe to inject directly into Groq LLM prompts without blowing token limits.

Public API
----------
    summaries = await get_summaries(soap_note, patient_id, db)

The returned list of strings is fed into the anomaly agent, differential
agent, and compliance service prompts (Steps 4 and 5).
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.embedding import VisitEmbedding
from models.visit import Visit
from schemas.pipeline import SOAPNote
from services.embedding import embed_text

log = logging.getLogger("medscribe.history_retrieval")

# Maximum number of past visits to retrieve and inject into the prompt.
_TOP_K = 5


def _soap_note_to_text(soap_note: SOAPNote) -> str:
    """Flatten a SOAPNote schema into a single string for embedding."""
    parts = []
    for field_name in ("subjective", "objective", "assessment", "plan"):
        field = getattr(soap_note, field_name, None)
        if field and field.text:
            parts.append(field.text)
    return " ".join(parts)


def _summarise_past_visit(visit: Visit, similarity: float) -> str:
    """Condense a past visit into a compact 3-line context string.

    Format keeps token count low while giving the LLM the key signals:
        Date: YYYY-MM-DD | Similarity: 0.87
        Assessment: <one-line>
        Plan: <one-line>
    """
    soap: dict = visit.soap_note or {}

    date_str = (
        visit.visit_date.strftime("%Y-%m-%d") if visit.visit_date else "unknown date"
    )

    def _field_text(field_name: str) -> str:
        field = soap.get(field_name, {})
        raw = field.get("text", "") if isinstance(field, dict) else str(field)
        # Truncate long fields to keep context injection small.
        return raw[:200].strip() or "not documented"

    assessment = _field_text("assessment")
    plan = _field_text("plan")

    return (
        f"Date: {date_str} | Similarity: {similarity:.2f}\n"
        f"Assessment: {assessment}\n"
        f"Plan: {plan}"
    )


async def get_summaries(
    soap_note: SOAPNote,
    patient_id: UUID,
    db: AsyncSession,
) -> list[str]:
    """Return up to 5 compact past-visit summaries ordered by semantic relevance.

    Steps:
    1. Embed the current SOAP note text (CPU, local model).
    2. Run pgvector cosine similarity search filtered to this patient.
    3. Load the matching Visit rows.
    4. Summarise each into a 3-line string.

    Returns an empty list if the patient has no prior visit embeddings.
    """
    # --- Step 1: embed the current SOAP note ---
    current_text = _soap_note_to_text(soap_note)
    if not current_text.strip():
        log.info("[history_retrieval] empty SOAP note — skipping history retrieval")
        return []

    query_vector: list[float] = embed_text(current_text)

    # --- Step 2: pgvector cosine similarity search ---
    # pgvector cosine distance operator: <=>
    # We want similarity = 1 - distance, so ORDER BY distance ASC gives us most similar first.
    similarity_expr = (
        1 - VisitEmbedding.full_note_embedding.cosine_distance(query_vector)
    )

    rows = (
        await db.execute(
            select(
                VisitEmbedding.visit_id,
                similarity_expr.label("similarity"),
            )
            .where(VisitEmbedding.patient_id == patient_id)
            .order_by(
                VisitEmbedding.full_note_embedding.cosine_distance(query_vector)
            )
            .limit(_TOP_K)
        )
    ).all()

    if not rows:
        log.info(
            "[history_retrieval] no prior embeddings for patient_id=%s", patient_id
        )
        return []

    visit_ids = [row.visit_id for row in rows]
    similarity_by_id = {row.visit_id: row.similarity for row in rows}

    # --- Step 3: load matching Visit rows ---
    visits_result = await db.execute(
        select(Visit).where(Visit.id.in_(visit_ids))
    )
    visits_by_id: dict[UUID, Visit] = {v.id: v for v in visits_result.scalars().all()}

    # --- Step 4: summarise in similarity order ---
    summaries: list[str] = []
    for vid in visit_ids:
        visit = visits_by_id.get(vid)
        if visit is None:
            continue
        sim = similarity_by_id.get(vid, 0.0)
        summaries.append(_summarise_past_visit(visit, sim))

    log.info(
        "[history_retrieval] retrieved %d past visits for patient_id=%s",
        len(summaries),
        patient_id,
    )
    return summaries
