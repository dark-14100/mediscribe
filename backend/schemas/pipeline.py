"""Pydantic schemas for every pipeline stage output.

These shapes are NON-NEGOTIABLE — the frontend, the database JSONB columns,
and the SSE event payloads all rely on them exactly as defined here.
See the master system prompt section "Key JSON Schemas".
"""
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.config import settings

# --- Transcription ---


class TranscriptLine(BaseModel):
    speaker: Literal["doctor", "patient"]
    text: str = Field(max_length=settings.MAX_TRANSCRIPT_LINE_CHARS)
    line_index: int


# --- SOAP / generic clinical note ---

# Was a Literal of the four SOAP fields; widened to a plain section-key string so
# non-SOAP note types (H&P, progress, discharge) can use their own section names.
# Values are validated against the active note template at the boundary, not here.
SOAPFieldName = str


class SOAPField(BaseModel):
    text: str = ""
    source_lines: list[int] = Field(default_factory=list)


# A note section is structurally identical to a SOAP field (text + citations).
NoteSection = SOAPField


class SOAPNote(BaseModel):
    subjective: SOAPField = Field(default_factory=SOAPField)
    objective: SOAPField = Field(default_factory=SOAPField)
    assessment: SOAPField = Field(default_factory=SOAPField)
    plan: SOAPField = Field(default_factory=SOAPField)


class ClinicalNote(BaseModel):
    """A note of any type as an ordered-by-template map of named sections.

    ``sections`` is keyed by the template's section keys (e.g. SOAP uses
    subjective/objective/assessment/plan; an H&P adds chief_complaint, hpi, …).
    The body persists as this flat ``sections`` dict in the existing
    ``visit.soap_note`` JSONB column, so SOAP visits are byte-for-byte unchanged.
    """

    note_type: str = "soap"
    sections: dict[str, SOAPField] = Field(default_factory=dict)

    @classmethod
    def from_sections(
        cls, note_type: str, sections: dict[str, Any] | None
    ) -> "ClinicalNote":
        parsed: dict[str, SOAPField] = {}
        for key, value in (sections or {}).items():
            if isinstance(value, SOAPField):
                parsed[key] = value
            elif isinstance(value, dict):
                parsed[key] = SOAPField.model_validate(value)
        return cls(note_type=note_type or "soap", sections=parsed)

    @classmethod
    def from_soap(cls, soap: SOAPNote) -> "ClinicalNote":
        return cls(
            note_type="soap",
            sections={
                "subjective": soap.subjective,
                "objective": soap.objective,
                "assessment": soap.assessment,
                "plan": soap.plan,
            },
        )

    def to_soap(self) -> SOAPNote:
        """Project this note onto the SOAP four fields for the analyst agents.

        For ``soap`` this is the identity. For other types the template's
        ``soap_projection`` concatenates the relevant sections into S/O/A/P so
        coding/compliance/differential/etc. keep working without per-type code.
        """
        from core.note_templates import soap_projection

        mapping = soap_projection(self.note_type)
        out: dict[str, SOAPField] = {}
        for soap_key, source_keys in mapping.items():
            texts: list[str] = []
            lines: list[int] = []
            for sk in source_keys:
                sec = self.sections.get(sk)
                if sec is None:
                    continue
                if sec.text.strip():
                    texts.append(sec.text.strip())
                lines.extend(sec.source_lines)
            out[soap_key] = SOAPField(
                text="\n\n".join(texts), source_lines=sorted(set(lines))
            )
        return SOAPNote(**out)


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


# --- De-identification (PHI stripped from text before the LLM) ---

DeidCategory = Literal[
    "name", "dob", "date", "phone", "email", "id", "url", "address", "other"
]


class DeidReport(BaseModel):
    """PHI-free summary of a de-identification pass. The reversible map of
    placeholder->original is PHI and is NEVER stored here — only counts."""

    applied: bool = False
    method: Literal["rules", "rules+ner"] = "rules"
    entity_count: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    residual_placeholders: int = 0


# --- Coding (advisory ICD-10 / CPT / E&M billing suggestions) ---

CodeSystem = Literal["ICD-10", "CPT", "E&M"]


class CodeSuggestion(BaseModel):
    """A single advisory billing/diagnosis code with its justification."""

    system: CodeSystem
    code: str
    description: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_field: SOAPFieldName | None = None
    evidence_lines: list[int] = Field(default_factory=list)
    rationale: str = ""


class CodingResult(BaseModel):
    """Advisory coding suggestions for a visit. NOT a final bill — the provider
    is responsible for the codes they submit."""

    icd10: list[CodeSuggestion] = Field(default_factory=list)
    cpt: list[CodeSuggestion] = Field(default_factory=list)
    em: CodeSuggestion | None = None
    patient_class: Literal["new", "established"] = "established"
    checked_with: Literal["rules", "rules+llm"] = "rules+llm"
    disclaimer: str = (
        "AI-suggested codes are advisory. The provider is responsible for "
        "final code selection before billing."
    )


class AcceptedCode(BaseModel):
    """A code the doctor has endorsed for this visit (Phase B).

    ``source_key`` (``"<system>:<original code>"``) links an accepted/edited code
    back to the AI suggestion it came from; it is ``None`` for codes added
    manually by the doctor.
    """

    system: CodeSystem
    code: str
    description: str = ""
    origin: Literal["ai", "edited", "manual"] = "ai"
    source_key: str | None = None


class CodingDecisions(BaseModel):
    """The doctor's confirm / edit / dismiss choices over the suggested codes.

    Persisted under ``soap_audit_trail.coding_decisions`` (no DB migration) and
    carried into the signed record. ``accepted`` is the provider-endorsed set;
    ``dismissed`` holds the ``"<system>:<code>"`` keys of suggestions rejected.
    """

    accepted: list[AcceptedCode] = Field(default_factory=list)
    dismissed: list[str] = Field(default_factory=list)


# --- Grounding (faithfulness of SOAP claims vs the transcript) ---

GroundingStatus = Literal["grounded", "partial", "ungrounded"]


class GroundingClaim(BaseModel):
    """A single SOAP sentence checked against its cited transcript lines."""

    field: SOAPFieldName
    text: str
    status: GroundingStatus
    confidence: float = Field(ge=0.0, le=1.0)
    cited_lines: list[int] = Field(default_factory=list)
    issue: str | None = None


class GroundingFieldResult(BaseModel):
    field: SOAPFieldName
    status: GroundingStatus
    confidence: float = Field(ge=0.0, le=1.0)
    cited_lines_valid: bool = True
    unsupported_claims: list[GroundingClaim] = Field(default_factory=list)


class GroundingResult(BaseModel):
    status: GroundingStatus
    confidence: float = Field(ge=0.0, le=1.0)
    fields: list[GroundingFieldResult] = Field(default_factory=list)
    checked_with: Literal["rules", "rules+llm"] = "rules"


# --- Request / response shapes for /pipeline/* routes ---


class TranscribeResponse(BaseModel):
    visit_id: uuid.UUID | None = None
    transcript: list[TranscriptLine] = Field(default_factory=list)
    audio_upload_queued: bool = False


class AudioUrlResponse(BaseModel):
    """Short-lived signed URL for fetching a visit's stored audio."""

    url: str
    expires_in: int


class PartialTranscriptResponse(BaseModel):
    """Near-live preview: the diarization-free text of the audio so far."""

    text: str = ""


class PipelineRunRequest(BaseModel):
    visit_id: uuid.UUID
    transcript: list[TranscriptLine] = Field(
        default_factory=list, max_length=settings.MAX_TRANSCRIPT_LINES
    )
    # Optional override of the visit's note type for this run (soap | hp |
    # progress | discharge). When omitted, the visit's stored note_type is used.
    note_type: str | None = None
    # Optional BCP-47 language for the generated note. When omitted, the visit's
    # stored language is used (default "en").
    language: str | None = None


# --- Final pipeline payload ---


class PipelinePayload(BaseModel):
    visit_id: uuid.UUID
    # `soap_note` is the SOAP projection (always the 4 fields) for back-compat;
    # `note` carries the real, template-shaped sections + the note type.
    note_type: str = "soap"
    language: str = "en"
    note: ClinicalNote | None = None
    soap_note: SOAPNote
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    differentials: list[Differential] = Field(default_factory=list)
    drift_flag: DriftFlag | None = None
    compliance_status: ComplianceStatus | None = None
    compliance_notes: list[ComplianceNote] = Field(default_factory=list)
    bias_flags: list[BiasFlag] = Field(default_factory=list)
    trajectory: TrajectoryResult | None = None
    grounding: GroundingResult | None = None
    deid: DeidReport | None = None
    coding: CodingResult | None = None
    # Names of pipeline steps that failed at runtime and fell back to a default.
    # Empty means every step completed normally; non-empty signals the result is
    # partial/degraded so the UI can flag it to the doctor.
    degraded_steps: list[str] = Field(default_factory=list)
