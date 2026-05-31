"""Patient CRUD + cached at-a-glance summary.

Doctor-scoped: a doctor sees only their own patients. Admins see all.
"""
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, require_doctor
from core.constants import ADMIN_ROLE
from db.session import get_db
from models.patient import Patient
from models.user import User
from models.visit import Visit
from schemas.patient import PatientCreate, PatientRead, PatientSummary
from services.cache import CacheClient, get_cache, patient_summary_key

log = logging.getLogger("medscribe.patients")
router = APIRouter(prefix="/patients", tags=["patients"])


def _is_admin(user: User) -> bool:
    return user.role == ADMIN_ROLE


async def _load_owned_patient(
    patient_id: UUID, user: User, db: AsyncSession
) -> Patient:
    """Load a patient that the current user is allowed to see, or 404."""
    stmt = select(Patient).where(Patient.id == patient_id)
    if not _is_admin(user):
        stmt = stmt.where(Patient.doctor_id == user.id)
    patient = await db.scalar(stmt)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


@router.post("", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
async def create_patient(
    payload: PatientCreate,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientRead:
    patient = Patient(
        full_name=payload.full_name,
        dob=payload.dob,
        gender=payload.gender,
        doctor_id=user.id,
        allergies=payload.allergies,
        active_medications=payload.active_medications,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    log.info("[patients] created patient_id=%s doctor_id=%s", patient.id, user.id)
    return PatientRead.model_validate(patient)


@router.get("", response_model=list[PatientRead])
async def list_patients(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PatientRead]:
    stmt = select(Patient).order_by(Patient.created_at.desc())
    if not _is_admin(user):
        stmt = stmt.where(Patient.doctor_id == user.id)
    result = await db.scalars(stmt)
    return [PatientRead.model_validate(p) for p in result.all()]


@router.get("/{patient_id}", response_model=PatientRead)
async def get_patient(
    patient_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PatientRead:
    patient = await _load_owned_patient(patient_id, user, db)
    return PatientRead.model_validate(patient)


@router.get("/{patient_id}/summary", response_model=PatientSummary)
async def get_patient_summary(
    patient_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[CacheClient, Depends(get_cache)],
) -> PatientSummary:
    """Returns the at-a-glance card. Cache-aside: hit Redis first, else build + cache."""
    cache_key = patient_summary_key(patient_id)

    cached = await cache.get(cache_key)
    if cached is not None:
        # Authorisation must still be enforced — never serve another doctor's cached card.
        cached_doctor_id = cached.get("doctor_id")
        if (
            _is_admin(user)
            or (cached_doctor_id and str(cached_doctor_id) == str(user.id))
        ):
            try:
                log.debug("[patients] summary cache HIT patient_id=%s", patient_id)
                return PatientSummary.model_validate(cached)
            except ValidationError:
                log.warning(
                    "[patients] invalid summary cache patient_id=%s — rebuilding",
                    patient_id,
                )
                await cache.invalidate(cache_key)
        # Cached but user can't see it — fall through to authoritative DB check.

    patient = await _load_owned_patient(patient_id, user, db)

    # Pull the most recent visits' dates and trajectory (newest first).
    visits_stmt = (
        select(Visit.visit_date, Visit.trajectory_direction, Visit.trajectory_score)
        .where(Visit.patient_id == patient.id)
        .order_by(desc(Visit.visit_date))
        .limit(3)
    )
    recent_visits = (await db.execute(visits_stmt)).all()
    last_visit_dates = [row.visit_date for row in recent_visits]

    latest_trajectory_direction: str | None = None
    latest_trajectory_score: float | None = None
    if recent_visits:
        latest_trajectory_direction = recent_visits[0].trajectory_direction
        latest_trajectory_score = recent_visits[0].trajectory_score

    # Trajectory confidence here is the latest score; the analytics route
    # computes a separate confidence based on visit count.
    trajectory_confidence = (
        int(round(latest_trajectory_score)) if latest_trajectory_score is not None else None
    )

    summary = PatientSummary(
        id=patient.id,
        full_name=patient.full_name,
        dob=patient.dob,
        gender=patient.gender,
        last_visit_dates=last_visit_dates,
        allergies=list(patient.allergies or []),
        active_medications=list(patient.active_medications or []),
        trajectory_direction=latest_trajectory_direction,
        trajectory_confidence=trajectory_confidence,
    )

    payload = summary.model_dump(mode="json")
    payload["doctor_id"] = str(patient.doctor_id)  # Stored only for cache auth checks.
    await cache.set(cache_key, payload)
    log.debug("[patients] summary cache MISS patient_id=%s (rebuilt)", patient_id)
    return summary
