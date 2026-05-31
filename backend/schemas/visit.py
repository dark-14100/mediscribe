"""Pydantic schemas for visit creation, full visit read, and note save/sign."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.coercion import coerce_json_list, coerce_str_list
from schemas.pipeline import SOAPNote


class VisitCreate(BaseModel):
    patient_id: uuid.UUID


class NoteSaveRequest(BaseModel):
    """Body of POST /notes/save — the (possibly doctor-edited) SOAP note."""

    soap_note: SOAPNote
    soap_audit_trail: dict[str, Any] = Field(default_factory=dict)
    doctor_modified_fields: list[str] = Field(default_factory=list)


class NoteSignResponse(BaseModel):
    visit_id: uuid.UUID
    is_signed: bool
    signed_at: datetime


class VisitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    visit_date: datetime

    raw_transcript: str | None = None
    audio_url: str | None = None

    soap_note: dict[str, Any] = Field(default_factory=dict)
    soap_audit_trail: dict[str, Any] = Field(default_factory=dict)

    anomalies: list[Any] = Field(default_factory=list)
    differentials: list[Any] = Field(default_factory=list)
    drift_flag: dict[str, Any] | None = None

    compliance_status: str | None = None
    compliance_notes: list[Any] = Field(default_factory=list)
    bias_flags: list[Any] = Field(default_factory=list)

    trajectory_score: float | None = None
    trajectory_direction: str | None = None
    trajectory_watch_zones: list[str] = Field(default_factory=list)

    is_signed: bool = False
    signed_at: datetime | None = None
    created_at: datetime

    @field_validator(
        "anomalies",
        "differentials",
        "compliance_notes",
        "bias_flags",
        mode="before",
    )
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[Any]:
        return coerce_json_list(value)

    @field_validator("trajectory_watch_zones", mode="before")
    @classmethod
    def _coerce_watch_zones(cls, value: Any) -> list[str]:
        return coerce_str_list(value)
