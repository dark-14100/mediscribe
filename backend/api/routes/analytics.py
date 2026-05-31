"""Analytics endpoints: trajectory and cognitive-load."""
import logging
from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.config import settings
from core.constants import ADMIN_ROLE
from db.session import get_db
from models.patient import Patient
from models.user import User
from schemas.pipeline import TrajectoryResult
from services.trajectory import compute as compute_trajectory

log = logging.getLogger("medscribe.analytics")
router = APIRouter(prefix="/analytics", tags=["analytics"])


class CognitiveLoadResponse(BaseModel):
    session_count: int = Field(ge=0)
    threshold: int = Field(ge=1)
    threshold_exceeded: bool
    as_of_date: date


@router.get(
    "/trajectory/{patient_id}",
    response_model=TrajectoryResult | None,
    summary="Trajectory direction + confidence + watch zones for a patient.",
)
async def get_trajectory(
    patient_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrajectoryResult | None:
    # Ownership check (admin sees all).
    stmt = select(Patient).where(Patient.id == patient_id)
    if user.role != ADMIN_ROLE:
        stmt = stmt.where(Patient.doctor_id == user.id)
    patient = await db.scalar(stmt)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")

    return await compute_trajectory(patient_id, drift_flag=None, db=db)


@router.get("/load", response_model=CognitiveLoadResponse)
async def get_cognitive_load(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CognitiveLoadResponse:
    """Returns the current doctor's session count for today and whether the
    cognitive-load threshold has been crossed.

    The counter is reset to 0 if ``last_session_date`` is anything other than
    today (i.e. first call of a new day rolls it over). This means a doctor
    who opens the dashboard at the start of a new day always sees a fresh count.
    """
    today = datetime.now(timezone.utc).date()
    count = user.session_count_today or 0

    if user.last_session_date is None or user.last_session_date < today:
        count = 0
        user.session_count_today = 0
        user.last_session_date = today
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception(
                "[analytics] failed to reset session count user_id=%s", user.id
            )
            raise
        log.info(
            "[analytics] reset session count for user_id=%s on %s", user.id, today
        )

    threshold = settings.COGNITIVE_LOAD_THRESHOLD
    return CognitiveLoadResponse(
        session_count=count,
        threshold=threshold,
        threshold_exceeded=count >= threshold,
        as_of_date=today,
    )
