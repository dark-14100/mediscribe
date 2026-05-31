"""Pydantic schemas for patient CRUD and the cached at-a-glance summary."""
import uuid
from datetime import date, datetime

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.coercion import coerce_str_list


class PatientCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    dob: date
    gender: str = Field(min_length=1, max_length=32)
    allergies: list[str] = Field(default_factory=list)
    active_medications: list[str] = Field(default_factory=list)


class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    dob: date
    gender: str
    doctor_id: uuid.UUID
    allergies: list[str]
    active_medications: list[str]
    created_at: datetime

    @field_validator("allergies", "active_medications", mode="before")
    @classmethod
    def _coerce_str_lists(cls, value: Any) -> list[str]:
        return coerce_str_list(value)


class PatientSummary(BaseModel):
    """Cached at-a-glance card returned by GET /patients/{id}/summary."""

    id: uuid.UUID
    full_name: str
    dob: date
    gender: str
    last_visit_dates: list[datetime] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    active_medications: list[str] = Field(default_factory=list)
    trajectory_direction: str | None = None
    trajectory_confidence: int | None = None

    @field_validator("allergies", "active_medications", mode="before")
    @classmethod
    def _coerce_str_lists(cls, value: Any) -> list[str]:
        return coerce_str_list(value)
