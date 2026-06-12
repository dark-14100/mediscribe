"""Differential diagnosis agent — pipeline Step 4b.

Produces a ranked list of alternative diagnoses from the current SOAP note only
(no patient history — avoids anchoring on past assumptions).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from schemas.pipeline import Differential, SOAPFieldName, SOAPNote
from services.groq_retry import chat_completion

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"

VALID_FIELDS: set[str] = {"subjective", "objective", "assessment", "plan"}

SYSTEM_PROMPT = """You are a clinical reasoning assistant helping a doctor consider differential diagnoses.

Given ONLY the current visit SOAP note, suggest 3 to 5 ranked alternative diagnoses
that could explain the presentation. Base reasoning on what is documented today —
do not invent symptoms or history not in the note.

Rules:
- Rank by clinical plausibility (highest confidence first).
- confidence: float between 0 and 1 (e.g. 0.74).
- contributing_fields: array of one or more of subjective, objective, assessment, plan
  that drove each suggestion (prefer subjective and objective when relevant).
- These are AI suggestions for the doctor's consideration — not definitive diagnoses.
- Return ONLY JSON: {"differentials": []} if the note is too sparse for meaningful differentials.
- Return ONLY JSON with no markdown:
  {"differentials": [{"diagnosis": "...", "confidence": 0.0, "contributing_fields": [...]}]}"""


def _coerce_soap(soap_note: SOAPNote | dict[str, Any]) -> SOAPNote:
    if isinstance(soap_note, SOAPNote):
        return soap_note
    return SOAPNote.model_validate(soap_note)


def _format_soap_for_prompt(soap: SOAPNote) -> str:
    lines: list[str] = []
    for key in ("subjective", "objective", "assessment", "plan"):
        field = getattr(soap, key)
        lines.append(f"{key.upper()}: {field.text.strip() or '(empty)'}")
    return "\n".join(lines)


def _normalize_contributing_fields(raw: Any) -> list[SOAPFieldName]:
    if not isinstance(raw, list):
        return ["subjective"]

    fields: list[SOAPFieldName] = []
    for item in raw:
        if isinstance(item, str) and item in VALID_FIELDS and item not in fields:
            fields.append(item)  # type: ignore[arg-type]
    return fields or ["subjective"]


def _parse_differential_item(raw: Any) -> Differential | None:
    if not isinstance(raw, dict):
        return None

    diagnosis = raw.get("diagnosis")
    if not isinstance(diagnosis, str) or not diagnosis.strip():
        return None

    confidence = raw.get("confidence", 0.0)
    if isinstance(confidence, bool):
        return None
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return None
    conf = max(0.0, min(1.0, conf))

    contributing = _normalize_contributing_fields(raw.get("contributing_fields", []))

    return Differential(
        diagnosis=diagnosis.strip(),
        confidence=conf,
        contributing_fields=contributing,
    )


def _parse_differentials_payload(parsed: dict[str, Any]) -> list[Differential]:
    raw_list = parsed.get("differentials", parsed.get("diagnoses", []))
    if not isinstance(raw_list, list):
        return []

    items: list[Differential] = []
    for entry in raw_list:
        diff = _parse_differential_item(entry)
        if diff is not None:
            items.append(diff)

    items.sort(key=lambda d: d.confidence, reverse=True)
    return items[:5]


async def diagnose(soap_note: SOAPNote | dict[str, Any]) -> list[Differential]:
    """Return ranked differential diagnoses for the current SOAP note."""
    soap = _coerce_soap(soap_note)
    user_message = f"CURRENT SOAP NOTE:\n{_format_soap_for_prompt(soap)}"

    logger.info("[DIFFERENTIAL_AGENT] Starting differential diagnosis")

    try:
        data = await chat_completion(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_tokens=1000,
            label="differential_agent",
        )
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("Groq returned no completion choices")

        content = choices[0].get("message", {}).get("content")
        if not content:
            raise ValueError("Groq returned empty completion content")

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response is not a JSON object")

        differentials = _parse_differentials_payload(parsed)
        logger.info("[DIFFERENTIAL_AGENT] Returned %d differentials", len(differentials))
        return differentials

    except json.JSONDecodeError as exc:
        logger.exception("[DIFFERENTIAL_AGENT] Invalid JSON from LLM")
        raise ValueError("LLM returned invalid JSON") from exc
    except Exception:
        logger.exception("[DIFFERENTIAL_AGENT] Differential diagnosis failed")
        raise
