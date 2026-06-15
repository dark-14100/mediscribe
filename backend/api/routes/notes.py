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
from core.audit import log_phi_access
from core.config import settings
from core.note_templates import normalize_note_type
from db.session import get_db
from models.patient import Patient
from models.user import User
from models.visit import Visit
from schemas.ehr import EhrExportRequest, EhrExportResult
from schemas.pipeline import ClinicalNote
from schemas.visit import (
    NoteSaveRequest,
    NoteSignRequest,
    NoteSignResponse,
    VisitRead,
)
from services.cache import CacheClient, get_cache, patient_summary_key
from services.compliance import check as compliance_check
from services.ehr_export import EhrExportError, export_note
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

    # Resolve the note body + type. Non-SOAP editors send `note_sections` +
    # `note_type`; SOAP callers send `soap_note`. Persist the flat sections dict.
    note_type = normalize_note_type(payload.note_type)
    if payload.note_sections is not None:
        sections = {k: v.model_dump(mode="json") for k, v in payload.note_sections.items()}
    elif payload.soap_note is not None:
        sections = payload.soap_note.model_dump(mode="json")
    else:
        sections = {}
    visit.note_type = note_type
    visit.soap_note = sections
    # The real (template-shaped) note for the compliance recheck below.
    note_for_checks = ClinicalNote.from_sections(note_type, sections)
    if payload.soap_audit_trail:
        visit.soap_audit_trail = payload.soap_audit_trail
    if payload.doctor_modified_fields:
        # Store the per-field 'doctor-modified' markers inside the audit trail
        # so we don't need a schema change just to record this.
        trail = dict(visit.soap_audit_trail or {})
        trail["doctor_modified_fields"] = payload.doctor_modified_fields
        visit.soap_audit_trail = trail
    if payload.coding_decisions is not None:
        # Phase B: persist the doctor's accept/edit/dismiss choices alongside the
        # AI suggestions already in the trail (no DB migration; same precedent as
        # doctor_modified_fields / grounding_ack).
        trail = dict(visit.soap_audit_trail or {})
        trail["coding_decisions"] = payload.coding_decisions.model_dump(mode="json")
        visit.soap_audit_trail = trail

    try:
        compliance = await compliance_check(note_for_checks)
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


def _grounding_blockers(trail: dict | None) -> list[str]:
    """Fields a doctor must acknowledge before signing under ``enforce``.

    Fail-closed: if the grounding result is missing (e.g. the step degraded), we
    return a sentinel so a missing check can't silently bypass the gate.
    """
    grounding = (trail or {}).get("grounding")
    if not isinstance(grounding, dict) or not grounding:
        return ["grounding check unavailable"]
    flagged = [
        str(f.get("field"))
        for f in grounding.get("fields", []) or []
        if isinstance(f, dict) and f.get("unsupported_claims")
    ]
    if grounding.get("status") == "ungrounded" and not flagged:
        flagged.append("note")
    return flagged


@router.post("/sign/{visit_id}", response_model=NoteSignResponse)
async def sign_note(
    visit_id: UUID,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[CacheClient, Depends(get_cache)],
    payload: NoteSignRequest | None = None,
) -> NoteSignResponse:
    """Mark a visit as signed. Returns 409 if already signed.

    Under ``GROUNDING_MODE=enforce``, signing a note that still has unverified
    claims requires ``acknowledged=true`` (else 412); the acknowledgement is
    stamped into the audit trail.
    """
    visit = await _load_my_visit(visit_id, user, db)

    if visit.is_signed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Note is already signed"
        )

    acknowledged = bool(payload and payload.acknowledged)
    if settings.GROUNDING_MODE.strip().lower() == "enforce":
        flagged = _grounding_blockers(visit.soap_audit_trail)
        if flagged and not acknowledged:
            raise HTTPException(
                status.HTTP_412_PRECONDITION_FAILED,
                detail={
                    "message": (
                        "This note has unverified statements. Review them and "
                        "acknowledge to sign."
                    ),
                    "flagged_fields": flagged,
                },
            )
        if flagged and acknowledged:
            trail = dict(visit.soap_audit_trail or {})
            trail["grounding_ack"] = {
                "by": str(user.id),
                "at": datetime.now(timezone.utc).isoformat(),
                "flagged_fields": flagged,
            }
            visit.soap_audit_trail = trail

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


def _existing_ehr_export(trail: dict | None) -> dict | None:
    block = (trail or {}).get("ehr_export")
    return block if isinstance(block, dict) else None


@router.post("/ehr-export/{visit_id}", response_model=EhrExportResult)
async def ehr_export(
    visit_id: UUID,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: EhrExportRequest | None = None,
) -> EhrExportResult:
    """File a signed note into the configured FHIR server as a DocumentReference.

    Gated on ``EHR_EXPORT_MODE`` (off by default) and a signed note. Idempotent:
    re-filing an already-exported visit is a no-op unless ``force=true``. The
    outcome is persisted into ``visit.soap_audit_trail.ehr_export`` and audited.
    """
    if (settings.EHR_EXPORT_MODE or "off").strip().lower() == "off":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="EHR export is not enabled on this server.",
        )

    visit = await _load_my_visit(visit_id, user, db)
    if not visit.is_signed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Sign the note before filing it to the EHR.",
        )

    force = bool(payload and payload.force)
    existing = _existing_ehr_export(visit.soap_audit_trail)
    if existing and existing.get("status") == "filed" and not force:
        return EhrExportResult.model_validate(existing)

    patient = await db.scalar(
        select(Patient).where(Patient.id == visit.patient_id)
    )
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")

    note_type = normalize_note_type(visit.note_type)
    sections = dict(visit.soap_note or {})

    result = EhrExportResult(
        status="failed",
        exported_by=str(user.id),
        exported_at=datetime.now(timezone.utc),
    )
    try:
        outcome = await export_note(
            note_type=note_type,
            sections=sections,
            patient=patient,
            doctor_name=user.full_name,
            signed_at=visit.signed_at,
            language=getattr(visit, "language", None),
        )
        result.status = "filed"
        result.document_reference_id = outcome["document_reference_id"]
        result.patient_fhir_id = outcome["patient_fhir_id"]
        result.fhir_base_url = outcome["fhir_base_url"]
    except EhrExportError as exc:
        result.error = str(exc)
    except Exception:  # noqa: BLE001 — never leak provider detail to the client
        log.exception("[notes] ehr export failed visit_id=%s", visit_id)
        result.error = "Could not file the note to the EHR. Please try again."

    # Persist the outcome (success or failure) into the audit trail.
    trail = dict(visit.soap_audit_trail or {})
    trail["ehr_export"] = result.model_dump(mode="json")
    visit.soap_audit_trail = trail
    await db.commit()

    log_phi_access(
        user_id=str(user.id),
        action="ehr_export",
        resource_type="visit",
        resource_id=str(visit.id),
    )

    if result.status != "filed":
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=result.error or "EHR export failed.",
        )
    log.info(
        "[notes] ehr export filed visit_id=%s doc=%s",
        visit.id,
        result.document_reference_id,
    )
    return result
