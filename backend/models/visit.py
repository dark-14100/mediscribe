"""Visit ORM model — one row per clinical session, central table of the system."""
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import array_str_type, jsonb_type


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    visit_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Captured inputs
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # SOAP output + audit
    soap_note: Mapped[dict[str, Any]] = mapped_column(
        jsonb_type(), nullable=False, default=dict
    )
    soap_audit_trail: Mapped[dict[str, Any]] = mapped_column(
        jsonb_type(), nullable=False, default=dict
    )

    # Intelligence agent outputs
    anomalies: Mapped[list[Any]] = mapped_column(
        jsonb_type(), nullable=False, default=list
    )
    differentials: Mapped[list[Any]] = mapped_column(
        jsonb_type(), nullable=False, default=list
    )
    drift_flag: Mapped[dict[str, Any] | None] = mapped_column(
        jsonb_type(), nullable=True
    )

    # Compliance + bias
    compliance_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    compliance_notes: Mapped[list[Any]] = mapped_column(
        jsonb_type(), nullable=False, default=list
    )
    bias_flags: Mapped[list[Any]] = mapped_column(
        jsonb_type(), nullable=False, default=list
    )

    # Trajectory
    trajectory_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    trajectory_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trajectory_watch_zones: Mapped[list[str]] = mapped_column(
        array_str_type(), nullable=False, default=list
    )

    # Sign-off
    is_signed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
