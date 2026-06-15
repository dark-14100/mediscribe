"""Compliance simulation service — pipeline Step 5.

Checks a generated SOAP note against HIPAA documentation requirements and
ICD-10 code coverage. Returns a ComplianceResult with a pass/warn/fail status
and a list of actionable notes for the doctor.

The pipeline route calls this as:
    from services.compliance import check
    result = await check(soap_note)
"""
from __future__ import annotations

import json
import logging

from typing import Any

from core.constants import HIPAA_DOCUMENTATION_CHECKLIST, ICD10_PRIMARY_CARE
from core.note_templates import (
    coding_sections,
    normalize_note_type,
    section_keys,
    section_labels,
)
from services.groq_retry import chat_completion
from services.groq_retry import GROQ_CHAT_URL as GROQ_CHAT_URL  # re-export for tests
from schemas.pipeline import ClinicalNote, ComplianceNote, ComplianceResult, SOAPNote

log = logging.getLogger("medscribe.compliance")

GROQ_MODEL = "llama-3.3-70b-versatile"

VALID_STATUSES: frozenset[str] = frozenset({"pass", "warn", "fail"})

_ICD10_BLOCK = "\n".join(f"  {code}: {desc}" for code, desc in ICD10_PRIMARY_CARE.items())
_HIPAA_BLOCK = "\n".join(f"  - {item}" for item in HIPAA_DOCUMENTATION_CHECKLIST)

SYSTEM_PROMPT = f"""\
You are a clinical documentation compliance reviewer. You will receive a SOAP \
note from a primary care visit and check it against HIPAA documentation \
requirements and ICD-10 coding standards.

HIPAA documentation checklist (ALL must be satisfied for a passing note):
{_HIPAA_BLOCK}

Common ICD-10 primary care codes for reference:
{_ICD10_BLOCK}

Evaluate the SOAP note on these four criteria:
1. Field completeness — all four SOAP fields (Subjective, Objective, Assessment, \
Plan) must contain meaningful clinical content (not empty or placeholder text).
2. ICD-10 coverage — the Assessment field must describe a condition that can be \
mapped to at least one ICD-10 code from the reference list or a plausible \
primary care diagnosis.
3. Plan disposition — the Plan field must include a specific follow-up instruction, \
referral, or disposition (e.g. "follow up in 2 weeks", "refer to cardiology", \
"return if symptoms worsen").
4. HIPAA markers — the note must satisfy all five checklist items above.

Status rules:
- "pass": all four criteria fully met, no issues found.
- "warn": minor omissions or suggestions exist but the note is safe to file.
- "fail": one or more required fields are empty, or the note is clinically \
unsafe to file as written (e.g. no plan, no assessment).

Return ONLY a JSON object with exactly this shape and no markdown:
{{
  "status": "pass" | "warn" | "fail",
  "notes": [
    {{
      "field": "<subjective|objective|assessment|plan|general>",
      "issue": "<one plain-English sentence describing the problem>",
      "suggestion": "<one plain-English sentence describing the fix>"
    }}
  ]
}}

Return "notes": [] when status is "pass".\
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_user_message(soap: SOAPNote) -> str:
    parts = []
    for field in ("subjective", "objective", "assessment", "plan"):
        text = getattr(soap, field).text.strip() or "(empty)"
        parts.append(f"{field.upper()}: {text}")
    return "SOAP NOTE TO REVIEW:\n" + "\n".join(parts)


def _extract_note(note: Any) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return (note_type, {section_key: {text, ...}}) for a ClinicalNote, SOAPNote,
    or dict — so SOAP callers/tests keep passing a SOAPNote."""
    if isinstance(note, ClinicalNote):
        return normalize_note_type(note.note_type), {
            k: {"text": v.text} for k, v in note.sections.items()
        }
    if isinstance(note, SOAPNote):
        return "soap", note.model_dump()
    if isinstance(note, dict):
        if isinstance(note.get("sections"), dict):
            return normalize_note_type(note.get("note_type")), note["sections"]
        return "soap", note
    return "soap", {}


def _labels_join(note_type: str, keys: list[str]) -> str:
    labels = section_labels(note_type)
    return ", ".join(labels.get(k, k) for k in keys) or "the documented sections"


def _build_user_message_generic(note_type: str, sections: dict[str, dict[str, Any]]) -> str:
    labels = section_labels(note_type)
    parts = []
    for key in section_keys(note_type):
        text = str((sections.get(key) or {}).get("text", "")).strip() or "(empty)"
        parts.append(f"{labels.get(key, key).upper()}: {text}")
    return "CLINICAL NOTE TO REVIEW:\n" + "\n".join(parts)


def _build_system_prompt_generic(note_type: str) -> str:
    coding = coding_sections(note_type)
    keys = section_keys(note_type)
    all_labels = _labels_join(note_type, keys)
    dx_label = _labels_join(note_type, coding["dx_sections"] or keys)
    px_label = _labels_join(note_type, coding["px_sections"] or keys[-1:])
    note_label = section_labels(note_type) and note_type.upper()
    return f"""\
You are a clinical documentation compliance reviewer. You will receive a \
{note_label} clinical note and check it against HIPAA documentation requirements \
and ICD-10 coding standards.

HIPAA documentation checklist (ALL must be satisfied for a passing note):
{_HIPAA_BLOCK}

Common ICD-10 primary care codes for reference:
{_ICD10_BLOCK}

Evaluate the note on these four criteria:
1. Field completeness — each documented section ({all_labels}) must contain \
meaningful clinical content (not empty or placeholder text).
2. ICD-10 coverage — the diagnosis section(s) ({dx_label}) must describe a \
condition mappable to at least one ICD-10 code from the reference list or a \
plausible diagnosis.
3. Disposition — the plan/disposition section(s) ({px_label}) must include a \
specific follow-up instruction, referral, or disposition.
4. HIPAA markers — the note must satisfy all checklist items above.

Status rules:
- "pass": all four criteria fully met, no issues found.
- "warn": minor omissions or suggestions exist but the note is safe to file.
- "fail": one or more required sections are empty, or the note is clinically \
unsafe to file as written.

Return ONLY a JSON object with exactly this shape and no markdown:
{{
  "status": "pass" | "warn" | "fail",
  "notes": [
    {{
      "field": "<section key or 'general'>",
      "issue": "<one plain-English sentence describing the problem>",
      "suggestion": "<one plain-English sentence describing the fix>"
    }}
  ]
}}

Return "notes": [] when status is "pass".\
"""


def _parse_compliance_note(raw: object) -> ComplianceNote | None:
    if not isinstance(raw, dict):
        return None
    field = raw.get("field")
    issue = raw.get("issue")
    suggestion = raw.get("suggestion")
    if not all(isinstance(v, str) and v.strip() for v in (field, issue, suggestion)):
        return None
    return ComplianceNote(
        field=str(field).strip(),
        issue=str(issue).strip(),
        suggestion=str(suggestion).strip(),
    )


def _parse_response(parsed: dict) -> ComplianceResult:
    status = parsed.get("status")
    if status not in VALID_STATUSES:
        log.warning(
            "[compliance] unexpected status value %r — defaulting to warn", status
        )
        status = "warn"

    raw_notes = parsed.get("notes", [])
    if not isinstance(raw_notes, list):
        raw_notes = []

    notes: list[ComplianceNote] = []
    for item in raw_notes:
        note = _parse_compliance_note(item)
        if note is not None:
            notes.append(note)

    return ComplianceResult(status=status, notes=notes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def check(soap_note: SOAPNote | ClinicalNote) -> ComplianceResult:
    """Run compliance simulation against a clinical note.

    Accepts a SOAPNote (back-compat; SOAP path is byte-for-byte unchanged) or a
    ClinicalNote of any type. Returns a ComplianceResult with status and notes.
    Never raises on a malformed LLM response — falls back to a "warn" result.
    Raises httpx.HTTPStatusError if the Groq API request fails.
    """
    note_type, sections = _extract_note(soap_note)
    if note_type == "soap" and isinstance(soap_note, SOAPNote):
        system_prompt = SYSTEM_PROMPT
        user_message = _build_user_message(soap_note)
    else:
        system_prompt = _build_system_prompt_generic(note_type)
        user_message = _build_user_message_generic(note_type, sections)
    log.info("[compliance] checking %s note for compliance", note_type)

    data = await chat_completion(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        max_tokens=800,
        label="compliance",
    )
    choices = data.get("choices") or []
    if not choices:
        log.warning("[compliance] Groq returned no choices — defaulting to warn")
        return ComplianceResult(status="warn", notes=[])

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        log.warning("[compliance] Groq returned empty content — defaulting to warn")
        return ComplianceResult(status="warn", notes=[])

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        log.warning("[compliance] Groq returned invalid JSON — defaulting to warn")
        return ComplianceResult(status="warn", notes=[])

    if not isinstance(parsed, dict):
        log.warning("[compliance] LLM response is not a JSON object — defaulting to warn")
        return ComplianceResult(status="warn", notes=[])

    result = _parse_response(parsed)
    log.info("[compliance] status=%s notes=%d", result.status, len(result.notes))
    return result
