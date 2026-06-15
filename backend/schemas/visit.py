"""Pydantic schemas for visit creation, full visit read, and note save/sign."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.coercion import (
    coerce_json_dict,
    coerce_json_list,
    coerce_optional_json_dict,
    coerce_str_list,
)
from schemas.pipeline import CodingDecisions, SOAPField, SOAPNote


class VisitCreate(BaseModel):
    patient_id: uuid.UUID
    note_type: str = "soap"
    language: str = "en"


class RecentVisitRead(BaseModel):
    """Lightweight visit row for cross-patient lists (sessions / dashboard).

    Carries the patient name so the client doesn't need a per-patient lookup.
    """

    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    patient_gender: str | None = None
    visit_date: datetime
    is_signed: bool = False
    compliance_status: str | None = None


class NoteSaveRequest(BaseModel):
    """Body of POST /notes/save — the (possibly doctor-edited) note.

    ``soap_note`` remains for SOAP callers/back-compat. For non-SOAP note types
    the editor sends the real sections in ``note_sections`` + ``note_type``;
    when present these take precedence for persistence.
    """

    soap_note: SOAPNote | None = None
    note_type: str = "soap"
    note_sections: dict[str, SOAPField] | None = None
    soap_audit_trail: dict[str, Any] = Field(default_factory=dict)
    doctor_modified_fields: list[str] = Field(default_factory=list)
    # Phase B coding: the doctor's confirm/edit/dismiss choices over suggested
    # codes. Optional so existing callers (which send no body field) are unaffected.
    coding_decisions: CodingDecisions | None = None


class NoteSignRequest(BaseModel):
    """Optional body for POST /notes/sign.

    Only consulted when ``GROUNDING_MODE=enforce`` and the note still has
    unverified claims: the doctor must set ``acknowledged=true`` to sign anyway.
    Defaulting to False keeps ``warn``/``off`` callers (which send no body)
    working unchanged.
    """

    acknowledged: bool = False


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

    note_type: str = "soap"
    language: str = "en"
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

    @field_validator("soap_note", "soap_audit_trail", mode="before")
    @classmethod
    def _coerce_dict_fields(cls, value: Any) -> dict[str, Any]:
        return coerce_json_dict(value)

    @field_validator("drift_flag", mode="before")
    @classmethod
    def _coerce_drift_flag(cls, value: Any) -> dict[str, Any] | None:
        return coerce_optional_json_dict(value)
