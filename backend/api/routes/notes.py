"""Note persistence and sign-off.

These endpoints are doctor-scoped and operate on existing visit rows.
The AI pipeline produces the initial SOAP via /pipeline/run; this file owns
what happens after the doctor reviews and either edits or signs the note.
"""
import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_doctor
from db.session import get_db
from models.user import User
from models.visit import Visit
from schemas.visit import NoteSaveRequest, NoteSignResponse, VisitRead
from services.cache import CacheClient, get_cache, patient_summary_key
from services.compliance import check as compliance_check
from services.visit_normalize import normalize_visit

log = logging.getLogger("medscribe.notes")
router = APIRouter(prefix="/notes", tags=["notes"])


async def _load_my_visit(visit_id: UUID, user: User, db: AsyncSession) -> Visit:
    visit = await db.scalar(
        select(Visit).where(Visit.id == visit_id, Visit.doctor_id == user.id)
    )
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Visit not found")
    return visit


def _queue_embed_visit(visit_id: UUID) -> None:
    """Best-effort queueing of the AI-team-owned embed_visit Celery task.

    The task itself (``workers.tasks.embed_visit``) is implemented by whoever
    owns ``services/embedding.py``. If it isn't registered yet we silently no-op
    so the backend remains operational while the AI side is still in flight.
    """
    try:
        from workers.celery_app import celery_app

        celery_app.send_task("workers.tasks.embed_visit", args=[str(visit_id)])
        log.info("[notes] queued embed_visit visit_id=%s", visit_id)
    except Exception as exc:  # noqa: BLE001 — cache/queue must not break sign-off
        log.warning("[notes] failed to queue embed_visit: %s", exc)


@router.post("/save/{visit_id}", response_model=VisitRead)
async def save_note(
    visit_id: UUID,
    payload: NoteSaveRequest,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[CacheClient, Depends(get_cache)],
) -> VisitRead:
    """Persist the doctor's SOAP note (and audit trail) to the visit row.

    Signed notes are immutable — returns 409 on further save attempts.
    Re-runs compliance on the edited note so the UI badge updates after save.
    """
    visit = await _load_my_visit(visit_id, user, db)

    if visit.is_signed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Note is already signed and cannot be modified",
        )

    visit.soap_note = payload.soap_note.model_dump(mode="json")
    if payload.soap_audit_trail:
        visit.soap_audit_trail = payload.soap_audit_trail
    if payload.doctor_modified_fields:
        # Store the per-field 'doctor-modified' markers inside the audit trail
        # so we don't need a schema change just to record this.
        trail = dict(visit.soap_audit_trail or {})
        trail["doctor_modified_fields"] = payload.doctor_modified_fields
        visit.soap_audit_trail = trail

    try:
        compliance = await compliance_check(payload.soap_note)
        visit.compliance_status = compliance.status
        visit.compliance_notes = [
            n.model_dump(mode="json") for n in compliance.notes
        ]
        log.info(
            "[notes] compliance after save visit_id=%s status=%s notes=%d",
            visit.id,
            compliance.status,
            len(compliance.notes),
        )
    except Exception:
        log.exception(
            "[notes] compliance check failed on save visit_id=%s", visit_id
        )

    await db.commit()
    await db.refresh(visit)
    normalize_visit(visit)

    # Invalidate the cached patient summary (its trajectory/medications may have moved).
    await cache.invalidate(patient_summary_key(visit.patient_id))

    # Fire-and-forget: ask the AI worker to refresh embeddings for this visit.
    _queue_embed_visit(visit.id)

    log.info(
        "[notes] saved visit_id=%s doctor_id=%s modified_fields=%s",
        visit.id,
        user.id,
        payload.doctor_modified_fields,
    )
    return VisitRead.model_validate(visit)


@router.post("/sign/{visit_id}", response_model=NoteSignResponse)
async def sign_note(
    visit_id: UUID,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[CacheClient, Depends(get_cache)],
) -> NoteSignResponse:
    """Mark a visit as signed. Returns 409 if already signed."""
    visit = await _load_my_visit(visit_id, user, db)

    if visit.is_signed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Note is already signed"
        )

    visit.is_signed = True
    visit.signed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(visit)

    await cache.invalidate(patient_summary_key(visit.patient_id))

    log.info("[notes] signed visit_id=%s doctor_id=%s", visit.id, user.id)
    return NoteSignResponse(
        visit_id=visit.id,
        is_signed=visit.is_signed,
        signed_at=visit.signed_at,
    )
