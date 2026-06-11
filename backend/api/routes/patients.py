"""Patient CRUD + cached at-a-glance summary.

Doctor-scoped: a doctor sees only their own patients. Admins see all.
"""
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, require_doctor
from core.constants import ADMIN_ROLE
from db.session import get_db
from models.patient import Patient
from models.user import User
from models.visit import Visit
from schemas.patient import (
    PatientCreate,
    PatientListItem,
    PatientRead,
    PatientSummary,
)
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


@router.get("/", response_model=list[PatientListItem], include_in_schema=False)
async def list_patients_trailing_slash(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    include: Annotated[str | None, Query()] = None,
) -> list[PatientListItem]:
    """Some clients request ``/patients/``; avoid matching ``/{patient_id}`` with an empty id."""
    return await list_patients(user, db, include)


@router.get("", response_model=list[PatientListItem])
async def list_patients(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    include: Annotated[str | None, Query()] = None,
) -> list[PatientListItem]:
    """List the doctor's patients.

    Pass ``?include=summary`` to enrich each row with trajectory + visit-count
    metadata in a single batched query (avoids per-patient summary fan-out).
    """
    stmt = select(Patient).order_by(Patient.created_at.desc())
    if not _is_admin(user):
        stmt = stmt.where(Patient.doctor_id == user.id)
    patients = (await db.scalars(stmt)).all()

    if include != "summary" or not patients:
        return [PatientListItem.model_validate(p) for p in patients]

    # One query for every visit belonging to these patients, newest first per
    # patient — reduced in Python into count / last-3-dates / latest trajectory.
    patient_ids = [p.id for p in patients]
    visits_stmt = (
        select(
            Visit.patient_id,
            Visit.visit_date,
            Visit.trajectory_direction,
            Visit.trajectory_score,
        )
        .where(Visit.patient_id.in_(patient_ids))
        .order_by(Visit.patient_id, desc(Visit.visit_date))
    )
    summary: dict = {}
    for row in (await db.execute(visits_stmt)).all():
        entry = summary.get(row.patient_id)
        if entry is None:
            # First (newest) row for this patient holds the latest trajectory.
            entry = {
                "count": 0,
                "dates": [],
                "direction": row.trajectory_direction,
                "score": row.trajectory_score,
            }
            summary[row.patient_id] = entry
        entry["count"] += 1
        if len(entry["dates"]) < 3:
            entry["dates"].append(row.visit_date)

    items: list[PatientListItem] = []
    for p in patients:
        item = PatientListItem.model_validate(p)
        s = summary.get(p.id)
        if s:
            score = s["score"]
            item = item.model_copy(
                update={
                    "visit_count": s["count"],
                    "last_visit_dates": s["dates"],
                    "trajectory_direction": s["direction"],
                    "trajectory_confidence": (
                        int(round(score)) if score is not None else None
                    ),
                }
            )
        items.append(item)
    return items


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

    visit_count = await db.scalar(
        select(func.count()).select_from(Visit).where(Visit.patient_id == patient.id)
    )

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
        visit_count=visit_count or 0,
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
