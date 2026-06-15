"""Coding agent — pipeline Step 5.5.

Turns a grounded clinical note into advisory billing/diagnosis codes: ICD-10
(diagnoses), CPT (procedures), and one office-visit E&M level appropriate to the
documented complexity. The note type's template decides which sections drive
diagnosis vs procedure codes (e.g. SOAP: ICD from Assessment, CPT from
Objective/Plan; discharge: ICD from the discharge diagnosis).

These are *suggestions only* — never a final bill. The provider is responsible
for the codes they submit. The agent follows the same contract as the other
LLM agents (one Groq call, strict JSON, never raises a bad-response error — it
degrades to an empty result so the pipeline keeps going).

The pipeline route calls this as:
    from services.coding import generate_codes
    result = await generate_codes(clinical_note, patient_class="established")
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.config import settings
from core.constants import (
    CPT_EM_REFERENCE,
    EM_CODES_ESTABLISHED,
    EM_CODES_NEW,
    ICD10_PRIMARY_CARE,
)
from core.note_templates import (
    coding_sections,
    normalize_note_type,
    section_keys,
    section_labels,
)
from schemas.pipeline import ClinicalNote, CodeSuggestion, CodingResult, SOAPNote
from services.groq_retry import chat_completion

log = logging.getLogger("medscribe.coding")

# ICD-10-CM: a letter, a digit, then an alphanumeric; optional dot + 1-4 more.
# 'U' is excluded by convention for the leading letter (matches ICD-10-CM ranges).
_ICD10_RE = re.compile(r"^[A-TV-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?$")
# CPT / E&M / HCPCS-numeric: 4-5 digits.
_CPT_RE = re.compile(r"^\d{4,5}$")

_ICD10_BLOCK = "\n".join(
    f"  {code}: {desc}" for code, desc in ICD10_PRIMARY_CARE.items()
)
_CPT_BLOCK = "\n".join(f"  {code}: {desc}" for code, desc in CPT_EM_REFERENCE.items())


def _extract_note(note: Any) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return (note_type, {section_key: {text, source_lines}}) for a ClinicalNote,
    SOAPNote, or dict — so SOAP callers/tests keep passing a SOAPNote."""
    if isinstance(note, ClinicalNote):
        return normalize_note_type(note.note_type), {
            k: {"text": v.text, "source_lines": list(v.source_lines)}
            for k, v in note.sections.items()
        }
    if isinstance(note, SOAPNote):
        return "soap", note.model_dump()
    if isinstance(note, dict):
        if isinstance(note.get("sections"), dict):
            return normalize_note_type(note.get("note_type")), note["sections"]
        return "soap", note
    return "soap", {}


def _dx_px_defaults(note_type: str) -> tuple[str, str]:
    """Default evidence section for diagnosis vs procedure codes."""
    coding = coding_sections(note_type)
    keys = section_keys(note_type)
    dx = (coding["dx_sections"] or [k for k in keys if "assess" in k] or keys)[0]
    px_list = coding["px_sections"] or [keys[-1]] if keys else []
    px = px_list[-1] if px_list else dx
    return dx, px


def _section_labels_join(note_type: str, keys: list[str]) -> str:
    labels = section_labels(note_type)
    return "/".join(labels.get(k, k).upper() for k in keys) or "the note"


def _build_system_prompt(note_type: str, patient_class: str, em_hint: str) -> str:
    coding = coding_sections(note_type)
    keys = section_keys(note_type)
    dx_default, px_default = _dx_px_defaults(note_type)
    dx_label = _section_labels_join(note_type, coding["dx_sections"] or [dx_default])
    px_label = _section_labels_join(note_type, coding["px_sections"] or [px_default])
    field_options = "|".join(keys)
    label = section_labels(note_type)  # for the example shapes
    return f"""\
You are a medical coding assistant. From the clinical note you receive, suggest \
billing and diagnosis codes for a {patient_class} patient office visit.

Reference ICD-10 codes (not exhaustive — use your knowledge too):
{_ICD10_BLOCK}

Reference CPT / E&M codes:
{_CPT_BLOCK}

Produce:
1. ICD-10 diagnosis codes derived from the {dx_label} section(s) (and supporting findings).
2. CPT procedure codes ONLY for procedures actually documented in {px_label} \
(do not invent procedures).
3. Exactly ONE office-visit E&M level appropriate to the documented complexity \
for a {patient_class} patient ({em_hint}).

For every code provide: code, description, confidence (0-1), the evidence_field \
section it came from ({field_options}), and a one-sentence rationale. These are \
advisory suggestions for the provider to review — NOT a final bill.

Return ONLY a JSON object with this exact shape and no markdown:
{{
  "icd10": [{{"code": "...", "description": "...", "confidence": 0.0, "evidence_field": "{dx_default}", "rationale": "..."}}],
  "cpt":   [{{"code": "...", "description": "...", "confidence": 0.0, "evidence_field": "{px_default}", "rationale": "..."}}],
  "em":     {{"code": "...", "description": "...", "confidence": 0.0, "evidence_field": "{px_default}", "rationale": "..."}}
}}
Use "icd10": [] / "cpt": [] when none apply, and "em": null if no office visit \
level fits.\
"""


def _format_note_for_prompt(note_type: str, sections: dict[str, dict[str, Any]]) -> str:
    labels = section_labels(note_type)
    parts = []
    for key in section_keys(note_type):
        text = str((sections.get(key) or {}).get("text", "")).strip() or "(empty)"
        parts.append(f"{labels.get(key, key).upper()}: {text}")
    return "CLINICAL NOTE TO CODE:\n" + "\n".join(parts)


def _field_source_lines(
    sections: dict[str, dict[str, Any]], field: str | None, valid: frozenset[str]
) -> tuple[str | None, list[int]]:
    """Resolve the evidence field + its transcript source_lines."""
    if field not in valid:
        return None, []
    raw = (sections.get(field) or {}).get("source_lines", [])
    lines = [int(n) for n in raw if isinstance(n, (int, float)) and not isinstance(n, bool)]
    return field, lines


def _clean_confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _parse_one(
    raw: Any, system: str, code_re: re.Pattern[str],
    sections: dict[str, dict[str, Any]], valid: frozenset[str],
    reference: dict[str, str], default_field: str,
) -> CodeSuggestion | None:
    if not isinstance(raw, dict):
        return None
    code = str(raw.get("code", "")).strip().upper()
    if not code_re.match(code):
        return None
    # Prefer the canonical reference description for known codes.
    description = reference.get(code) or str(raw.get("description", "")).strip()
    field = raw.get("evidence_field")
    if field not in valid:
        field = default_field
    evidence_field, evidence_lines = _field_source_lines(sections, field, valid)
    return CodeSuggestion(
        system=system,  # type: ignore[arg-type]
        code=code,
        description=description,
        confidence=_clean_confidence(raw.get("confidence", 0.0)),
        evidence_field=evidence_field,  # type: ignore[arg-type]
        evidence_lines=evidence_lines,
        rationale=str(raw.get("rationale", "")).strip(),
    )


def _dedupe(items: list[CodeSuggestion]) -> list[CodeSuggestion]:
    seen: set[str] = set()
    out: list[CodeSuggestion] = []
    for item in items:
        if item.code in seen:
            continue
        seen.add(item.code)
        out.append(item)
    return out


def _parse_em(
    raw: Any, sections: dict[str, dict[str, Any]], valid: frozenset[str],
    em_default: str, patient_class: str,
) -> CodeSuggestion | None:
    suggestion = _parse_one(
        raw, "E&M", _CPT_RE, sections, valid, CPT_EM_REFERENCE, em_default
    )
    if suggestion is None:
        return None
    valid = EM_CODES_NEW if patient_class == "new" else EM_CODES_ESTABLISHED
    if suggestion.code not in valid:
        log.info(
            "[coding] dropping E&M %s — not valid for %s patient",
            suggestion.code,
            patient_class,
        )
        return None
    return suggestion


def _parse_response(
    parsed: dict[str, Any], note_type: str,
    sections: dict[str, dict[str, Any]], patient_class: str
) -> CodingResult:
    valid = frozenset(section_keys(note_type))
    dx_default, px_default = _dx_px_defaults(note_type)
    icd10 = _dedupe(
        [
            s
            for s in (
                _parse_one(
                    r, "ICD-10", _ICD10_RE, sections, valid, ICD10_PRIMARY_CARE, dx_default
                )
                for r in (parsed.get("icd10") or [])
                if isinstance(parsed.get("icd10"), list)
            )
            if s is not None
        ]
    )
    cpt = _dedupe(
        [
            s
            for s in (
                _parse_one(
                    r, "CPT", _CPT_RE, sections, valid, CPT_EM_REFERENCE, px_default
                )
                for r in (parsed.get("cpt") or [])
                if isinstance(parsed.get("cpt"), list)
            )
            if s is not None
        ]
    )

    # Keep the panel focused: cap combined ICD-10 + CPT, highest-confidence first
    # across both systems (so a high-confidence CPT isn't crowded out by
    # low-confidence diagnoses, or vice versa).
    max_codes = max(1, settings.CODING_MAX_CODES)
    combined = sorted(icd10 + cpt, key=lambda s: s.confidence, reverse=True)[:max_codes]
    icd10 = [s for s in combined if s.system == "ICD-10"]
    cpt = [s for s in combined if s.system == "CPT"]

    em = (
        _parse_em(parsed.get("em"), sections, valid, px_default, patient_class)
        if settings.CODING_INCLUDE_EM
        else None
    )

    return CodingResult(
        icd10=icd10,
        cpt=cpt,
        em=em,
        patient_class=patient_class,  # type: ignore[arg-type]
    )


async def generate_codes(
    note: SOAPNote | ClinicalNote | dict[str, Any], *, patient_class: str = "established"
) -> CodingResult:
    """Return advisory ICD-10 / CPT / E&M suggestions for a clinical note.

    Accepts a SOAPNote (back-compat), a ClinicalNote of any type, or a dict.
    Never raises on a malformed LLM response — returns an empty CodingResult.
    Raises httpx.HTTPStatusError only if the Groq request itself fails (handled
    by the pipeline's _maybe_call wrapper).
    """
    note_type, sections = _extract_note(note)
    patient_class = "new" if str(patient_class).lower() == "new" else "established"
    em_hint = (
        "new-patient codes 99202-99205"
        if patient_class == "new"
        else "established-patient codes 99211-99215"
    )
    system_prompt = _build_system_prompt(note_type, patient_class, em_hint)

    log.info("[coding] generating codes for %s patient (%s note)", patient_class, note_type)

    data = await chat_completion(
        model=settings.CODING_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _format_note_for_prompt(note_type, sections)},
        ],
        response_format={"type": "json_object"},
        max_tokens=900,
        label="coding",
    )

    choices = data.get("choices") or []
    if not choices:
        log.warning("[coding] Groq returned no choices — empty coding result")
        return CodingResult(patient_class=patient_class)  # type: ignore[arg-type]
    content = choices[0].get("message", {}).get("content", "")
    if not content:
        log.warning("[coding] Groq returned empty content — empty coding result")
        return CodingResult(patient_class=patient_class)  # type: ignore[arg-type]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        log.warning("[coding] Groq returned invalid JSON — empty coding result")
        return CodingResult(patient_class=patient_class)  # type: ignore[arg-type]
    if not isinstance(parsed, dict):
        log.warning("[coding] LLM response is not a JSON object — empty coding result")
        return CodingResult(patient_class=patient_class)  # type: ignore[arg-type]

    result = _parse_response(parsed, note_type, sections, patient_class)
    log.info(
        "[coding] icd10=%d cpt=%d em=%s",
        len(result.icd10),
        len(result.cpt),
        result.em.code if result.em else None,
    )
    return result
