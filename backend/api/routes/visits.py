"""Visit endpoints: create an empty session row, read one, list per patient."""
import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, require_doctor
from core.constants import ADMIN_ROLE
from db.session import get_db
from models.patient import Patient
from models.user import User
from models.visit import Visit
from schemas.visit import VisitCreate, VisitRead

log = logging.getLogger("medscribe.visits")
router = APIRouter(prefix="/visits", tags=["visits"])


def _is_admin(user: User) -> bool:
    return user.role == ADMIN_ROLE


async def _load_owned_patient(
    patient_id: UUID, user: User, db: AsyncSession
) -> Patient:
    stmt = select(Patient).where(Patient.id == patient_id)
    if not _is_admin(user):
        stmt = stmt.where(Patient.doctor_id == user.id)
    patient = await db.scalar(stmt)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


async def _load_owned_visit(
    visit_id: UUID, user: User, db: AsyncSession
) -> Visit:
    stmt = select(Visit).where(Visit.id == visit_id)
    if not _is_admin(user):
        stmt = stmt.where(Visit.doctor_id == user.id)
    visit = await db.scalar(stmt)
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Visit not found")
    return visit


def _bump_session_count(user: User) -> None:
    """Increment the doctor's cognitive-load counter, resetting on day rollover."""
    today = datetime.now(timezone.utc).date()
    if user.last_session_date is None or user.last_session_date < today:
        user.session_count_today = 1
    else:
        user.session_count_today = (user.session_count_today or 0) + 1
    user.last_session_date = today


@router.post("", response_model=VisitRead, status_code=status.HTTP_201_CREATED)
async def create_visit(
    payload: VisitCreate,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Visit:
    # Validate ownership of the patient before creating the visit.
    await _load_owned_patient(payload.patient_id, user, db)

    visit = Visit(
        patient_id=payload.patient_id,
        doctor_id=user.id,
    )
    db.add(visit)

    # A session starts when the visit row is created — this is what the
    # cognitive-load nudge measures.
    _bump_session_count(user)

    await db.commit()
    await db.refresh(visit)
    log.info(
        "[visits] created visit_id=%s patient_id=%s doctor_id=%s "
        "session_count_today=%d",
        visit.id,
        visit.patient_id,
        visit.doctor_id,
        user.session_count_today,
    )
    return visit


@router.get("/{visit_id}", response_model=VisitRead)
async def get_visit(
    visit_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Visit:
    return await _load_owned_visit(visit_id, user, db)


@router.get("/patient/{patient_id}", response_model=list[VisitRead])
async def list_patient_visits(
    patient_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Visit]:
    """Paginated list of visits for a patient, newest first.

    Returns 404 if the patient doesn't exist or isn't visible to the caller —
    same response as a non-existent patient to avoid leaking ownership info.
    """
    await _load_owned_patient(patient_id, user, db)

    stmt = (
        select(Visit)
        .where(Visit.patient_id == patient_id)
        .order_by(desc(Visit.visit_date))
        .limit(limit)
        .offset(offset)
    )
    result = await db.scalars(stmt)
    return list(result.all())
