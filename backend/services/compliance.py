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

import httpx

from core.config import settings
from core.constants import HIPAA_DOCUMENTATION_CHECKLIST, ICD10_PRIMARY_CARE
from services.groq_retry import call_with_retries
from schemas.pipeline import ComplianceNote, ComplianceResult, ComplianceStatus, SOAPNote

log = logging.getLogger("medscribe.compliance")

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
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


async def check(soap_note: SOAPNote) -> ComplianceResult:
    """Run compliance simulation against the SOAP note.

    Returns a ComplianceResult with status and list of notes.
    Never raises on a malformed LLM response — falls back to a "warn" result.
    Raises httpx.HTTPStatusError if the Groq API request fails.
    """
    user_message = _build_user_message(soap_note)
    log.info("[compliance] checking SOAP note for compliance")

    async def _request() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                    "max_tokens": 800,
                },
                timeout=settings.GROQ_TIMEOUT_SECONDS,
            )
        if response.status_code != 200:
            log.error(
                "[compliance] Groq API error %s: %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()
        return response

    response = await call_with_retries(_request, label="compliance")

    data = response.json()
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
