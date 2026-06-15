"""Clinical note-type templates — the single source of truth for note shapes.

A note type is just data: an ordered list of sections (key + label), per-section
generator guidance, grounding weights, a mapping that projects the note onto the
classic SOAP four fields (so the analyst/coding/compliance agents keep working
unchanged), and a coding hint for which sections drive diagnosis vs procedure
codes.

This module is intentionally dependency-free (pure data + helpers) so it can be
imported by schemas, services, the eval harness, and the pipeline without pulling
in heavy deps.
"""
from __future__ import annotations

from typing import Final

DEFAULT_NOTE_TYPE: Final[str] = "soap"

# Each template:
#   label             — human label for the UI/title
#   sections          — ordered [(key, label), ...]
#   guidance          — {key: one-line instruction for the generator prompt}
#   grounding_weights — {key: weight} (default 1.0; diagnosis/plan-like sections 2.0)
#   soap_projection   — {soap_key: [section_key, ...]} to fold this note into SOAP
#                       for the analyst agents (identity for "soap")
#   coding            — {"dx_sections": [...], "px_sections": [...]} (used in coding B)
NOTE_TEMPLATES: Final[dict[str, dict]] = {
    "soap": {
        "label": "SOAP note",
        "sections": [
            ("subjective", "Subjective"),
            ("objective", "Objective"),
            ("assessment", "Assessment"),
            ("plan", "Plan"),
        ],
        "guidance": {
            "subjective": "what the patient reports (symptoms, history, concerns)",
            "objective": "exam findings, vitals, and measurable observations",
            "assessment": "the clinical impression / diagnosis",
            "plan": "next steps: treatment, tests, referrals, follow-up",
        },
        "grounding_weights": {"assessment": 2.0, "plan": 2.0},
        "soap_projection": {
            "subjective": ["subjective"],
            "objective": ["objective"],
            "assessment": ["assessment"],
            "plan": ["plan"],
        },
        "coding": {"dx_sections": ["assessment"], "px_sections": ["objective", "plan"]},
    },
    "hp": {
        "label": "History & Physical",
        "sections": [
            ("chief_complaint", "Chief Complaint"),
            ("hpi", "History of Present Illness"),
            ("pmh", "Past Medical History"),
            ("ros", "Review of Systems"),
            ("exam", "Physical Exam"),
            ("assessment", "Assessment"),
            ("plan", "Plan"),
        ],
        "guidance": {
            "chief_complaint": "the patient's main reason for the visit, in brief",
            "hpi": "the story of the present illness (onset, duration, severity, context)",
            "pmh": "relevant past medical, surgical, family, and social history",
            "ros": "a systems review of pertinent positives and negatives",
            "exam": "physical examination findings and vitals",
            "assessment": "the clinical impression / diagnosis",
            "plan": "treatment, tests, referrals, and follow-up",
        },
        "grounding_weights": {"assessment": 2.0, "plan": 2.0},
        "soap_projection": {
            "subjective": ["chief_complaint", "hpi", "pmh", "ros"],
            "objective": ["exam"],
            "assessment": ["assessment"],
            "plan": ["plan"],
        },
        "coding": {"dx_sections": ["assessment"], "px_sections": ["exam", "plan"]},
    },
    "progress": {
        "label": "Progress note",
        "sections": [
            ("interval_history", "Interval History"),
            ("exam", "Exam / Findings"),
            ("assessment", "Assessment"),
            ("plan", "Plan"),
        ],
        "guidance": {
            "interval_history": "what changed since the last visit (a brief update)",
            "exam": "current exam findings and vitals",
            "assessment": "the updated clinical impression",
            "plan": "adjustments to treatment, tests, and follow-up",
        },
        "grounding_weights": {"assessment": 2.0, "plan": 2.0},
        "soap_projection": {
            "subjective": ["interval_history"],
            "objective": ["exam"],
            "assessment": ["assessment"],
            "plan": ["plan"],
        },
        "coding": {"dx_sections": ["assessment"], "px_sections": ["exam", "plan"]},
    },
    "discharge": {
        "label": "Discharge summary",
        "sections": [
            ("admission_dx", "Admission Diagnosis"),
            ("discharge_dx", "Discharge Diagnosis"),
            ("hospital_course", "Hospital Course"),
            ("discharge_meds", "Discharge Medications"),
            ("followup", "Follow-up Instructions"),
        ],
        "guidance": {
            "admission_dx": "the diagnosis the patient was admitted for",
            "discharge_dx": "the final diagnosis/diagnoses at discharge",
            "hospital_course": "a summary of the stay: treatments, response, key events",
            "discharge_meds": "medications to continue/start/stop at discharge",
            "followup": "follow-up appointments, instructions, and warning signs",
        },
        "grounding_weights": {"discharge_dx": 2.0, "followup": 2.0},
        "soap_projection": {
            "subjective": ["admission_dx"],
            "objective": ["hospital_course"],
            "assessment": ["discharge_dx"],
            "plan": ["discharge_meds", "followup"],
        },
        "coding": {
            "dx_sections": ["discharge_dx", "admission_dx"],
            "px_sections": ["hospital_course"],
        },
    },
}


def normalize_note_type(note_type: str | None) -> str:
    """Return a known note-type key, falling back to the default."""
    key = (note_type or "").strip().lower()
    return key if key in NOTE_TEMPLATES else DEFAULT_NOTE_TYPE


def get_template(note_type: str | None) -> dict:
    return NOTE_TEMPLATES[normalize_note_type(note_type)]


def section_keys(note_type: str | None) -> list[str]:
    return [key for key, _ in get_template(note_type)["sections"]]


def section_labels(note_type: str | None) -> dict[str, str]:
    return {key: label for key, label in get_template(note_type)["sections"]}


def grounding_weights(note_type: str | None) -> dict[str, float]:
    return dict(get_template(note_type).get("grounding_weights", {}))


def soap_projection(note_type: str | None) -> dict[str, list[str]]:
    return dict(get_template(note_type)["soap_projection"])


def note_type_choices() -> list[dict[str, str]]:
    """[{key, label}, ...] for selectors/clients."""
    return [{"key": key, "label": tpl["label"]} for key, tpl in NOTE_TEMPLATES.items()]
