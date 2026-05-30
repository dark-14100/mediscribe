"""Pydantic schemas for user registration, login, and JWT responses."""
import uuid
from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.constants import ALLOWED_ROLES, DOCTOR_ROLE


def _normalize_email(value: str) -> str:
    """Accept demo/local domains (.test, .local) used in seeds and hackathon docs."""
    try:
        return validate_email(
            value,
            check_deliverability=False,
            test_environment=True,
        ).normalized
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: str = Field(default=DOCTOR_ROLE, pattern=f"^({'|'.join(ALLOWED_ROLES)})$")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserLogin(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    role: str
    exp: int
