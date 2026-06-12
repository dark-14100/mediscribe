"""Pydantic schemas for every pipeline stage output.

These shapes are NON-NEGOTIABLE — the frontend, the database JSONB columns,
and the SSE event payloads all rely on them exactly as defined here.
See the master system prompt section "Key JSON Schemas".
"""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from core.config import settings

# --- Transcription ---


class TranscriptLine(BaseModel):
    speaker: Literal["doctor", "patient"]
    text: str = Field(max_length=settings.MAX_TRANSCRIPT_LINE_CHARS)
    line_index: int


# --- SOAP ---

SOAPFieldName = Literal["subjective", "objective", "assessment", "plan"]


class SOAPField(BaseModel):
    text: str = ""
    source_lines: list[int] = Field(default_factory=list)


class SOAPNote(BaseModel):
    subjective: SOAPField = Field(default_factory=SOAPField)
    objective: SOAPField = Field(default_factory=SOAPField)
    assessment: SOAPField = Field(default_factory=SOAPField)
    plan: SOAPField = Field(default_factory=SOAPField)


# --- Anomalies ---

AnomalySeverity = Literal["high", "medium", "low"]
AnomalyType = Literal["drug_interaction", "contradictory_symptom", "outlier_vital"]


class AnomalyFlag(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    severity: AnomalySeverity
    type: AnomalyType
    description: str
    source_line: int


# --- Differentials ---


class Differential(BaseModel):
    diagnosis: str
    confidence: float = Field(ge=0.0, le=1.0)
    contributing_fields: list[SOAPFieldName]


# --- Drift ---

DriftDirection = Literal[
    "increased_pain_descriptors",
    "increased_negative_affect",
    "no_significant_drift",
]


class DriftFlag(BaseModel):
    flagged: bool
    direction: DriftDirection | None = None
    delta: float
    threshold: float


# --- Compliance ---

ComplianceStatus = Literal["pass", "warn", "fail"]


class ComplianceNote(BaseModel):
    field: str
    issue: str
    suggestion: str


class ComplianceResult(BaseModel):
    status: ComplianceStatus
    notes: list[ComplianceNote] = Field(default_factory=list)


# --- Bias ---

BiasType = Literal["gender_bias", "age_bias", "socioeconomic_bias"]


class BiasFlag(BaseModel):
    phrase: str
    type: BiasType
    suggested_rewrite: str


# --- Trajectory ---

TrajectoryDirection = Literal["up", "stable", "down"]


class TrajectoryResult(BaseModel):
    direction: TrajectoryDirection
    score: float
    confidence: int = Field(ge=0, le=100)
    watch_zones: list[str] = Field(default_factory=list)
    computed_from_visits: int


# --- Request / response shapes for /pipeline/* routes ---


class TranscribeResponse(BaseModel):
    visit_id: uuid.UUID | None = None
    transcript: list[TranscriptLine] = Field(default_factory=list)
    audio_upload_queued: bool = False


class AudioUrlResponse(BaseModel):
    """Short-lived signed URL for fetching a visit's stored audio."""

    url: str
    expires_in: int


class PipelineRunRequest(BaseModel):
    visit_id: uuid.UUID
    transcript: list[TranscriptLine] = Field(
        default_factory=list, max_length=settings.MAX_TRANSCRIPT_LINES
    )


# --- Final pipeline payload ---


class PipelinePayload(BaseModel):
    visit_id: uuid.UUID
    soap_note: SOAPNote
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    differentials: list[Differential] = Field(default_factory=list)
    drift_flag: DriftFlag | None = None
    compliance_status: ComplianceStatus | None = None
    compliance_notes: list[ComplianceNote] = Field(default_factory=list)
    bias_flags: list[BiasFlag] = Field(default_factory=list)
    trajectory: TrajectoryResult | None = None
    # Names of pipeline steps that failed at runtime and fell back to a default.
    # Empty means every step completed normally; non-empty signals the result is
    # partial/degraded so the UI can flag it to the doctor.
    degraded_steps: list[str] = Field(default_factory=list)
