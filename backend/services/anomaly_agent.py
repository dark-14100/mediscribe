"""Anomaly detection agent — pipeline Step 4a.

Reads the current SOAP note, RAG history summaries, and active medications;
flags drug interactions, contradictory symptoms, and outlier vitals.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from core.config import settings
from schemas.pipeline import AnomalyFlag, SOAPNote

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

VALID_SEVERITIES: set[str] = {"high", "medium", "low"}
VALID_TYPES: set[str] = {
    "drug_interaction",
    "contradictory_symptom",
    "outlier_vital",
}

SYSTEM_PROMPT = """You are a clinical safety assistant reviewing a SOAP note from today's visit.

Compare the current note against the patient's medication list and summarized past visits.
Flag clinically suspicious findings the doctor might miss in the moment.

Check for exactly these three categories:
1. drug_interaction — a medication in today's plan clashes with active_medications
   (e.g. warfarin + aspirin, ACE inhibitor + potassium supplement).
2. contradictory_symptom — today's subjective/objective contradicts documented history
   (e.g. denies chest pain today but prior visit documented stable angina).
3. outlier_vital — BP, HR, SpO2, temperature, or other vitals outside plausible normal
   ranges for this patient (use demographics implied in the note when available).

Rules:
- Only flag issues supported by the SOAP text or clear conflict with history/meds.
- severity: "high" (immediate safety risk), "medium" (needs attention), "low" (worth noting).
- type: exactly one of drug_interaction, contradictory_symptom, outlier_vital.
- source_line: integer transcript line most relevant (use SOAP source_lines when provided;
  otherwise use 1).
- description: one clear plain-English sentence for the clinician.
- Return ONLY JSON: {"anomalies": []} when nothing is suspicious.
- Return ONLY JSON with no markdown: {"anomalies": [{...}, ...]}"""


def _coerce_soap(soap_note: SOAPNote | dict[str, Any]) -> SOAPNote:
    if isinstance(soap_note, SOAPNote):
        return soap_note
    return SOAPNote.model_validate(soap_note)


def _format_soap_for_prompt(soap: SOAPNote) -> str:
    lines: list[str] = []
    for key in ("subjective", "objective", "assessment", "plan"):
        field = getattr(soap, key)
        src = ""
        if field.source_lines:
            src = f" (transcript lines: {field.source_lines})"
        lines.append(f"{key.upper()}: {field.text.strip() or '(empty)'}{src}")
    return "\n".join(lines)


def _format_history_block(summaries: list[str]) -> str:
    if not summaries:
        return "No prior visit summaries available."
    blocks = [f"--- Past visit {i + 1} ---\n{s}" for i, s in enumerate(summaries)]
    return "\n\n".join(blocks)


def _format_medications(medications: list[str]) -> str:
    if not medications:
        return "None documented."
    return "\n".join(f"- {med}" for med in medications)


def _parse_anomaly_item(raw: Any) -> AnomalyFlag | None:
    if not isinstance(raw, dict):
        return None

    severity = raw.get("severity")
    type_ = raw.get("type")
    description = raw.get("description")
    source_line = raw.get("source_line", raw.get("source_lines"))

    if severity not in VALID_SEVERITIES or type_ not in VALID_TYPES:
        return None
    if not isinstance(description, str) or not description.strip():
        return None

    line_num = 1
    if isinstance(source_line, list) and source_line:
        first = source_line[0]
        if isinstance(first, (int, float)) and not isinstance(first, bool):
            line_num = int(first)
    elif isinstance(source_line, (int, float)) and not isinstance(source_line, bool):
        line_num = int(source_line)

    flag_id = raw.get("id")
    if not isinstance(flag_id, str) or not flag_id.strip():
        flag_id = str(uuid.uuid4())

    return AnomalyFlag(
        id=flag_id,
        severity=severity,  # type: ignore[arg-type]
        type=type_,  # type: ignore[arg-type]
        description=description.strip(),
        source_line=line_num,
    )


def _parse_anomalies_payload(parsed: dict[str, Any]) -> list[AnomalyFlag]:
    raw_list = parsed.get("anomalies")
    if raw_list is None:
        raw_list = parsed.get("flags", parsed.get("anomaly_flags", []))
    if not isinstance(raw_list, list):
        return []

    flags: list[AnomalyFlag] = []
    for item in raw_list:
        flag = _parse_anomaly_item(item)
        if flag is not None:
            flags.append(flag)
    return flags


async def detect(
    soap_note: SOAPNote | dict[str, Any],
    history_summaries: list[str],
    active_medications: list[str],
) -> list[AnomalyFlag]:
    """Detect clinical anomalies from SOAP + history + medications."""
    soap = _coerce_soap(soap_note)
    user_message = (
        "CURRENT SOAP NOTE:\n"
        f"{_format_soap_for_prompt(soap)}\n\n"
        "ACTIVE MEDICATIONS:\n"
        f"{_format_medications(active_medications)}\n\n"
        "PAST VISIT SUMMARIES (RAG):\n"
        f"{_format_history_block(history_summaries)}"
    )

    logger.info("[ANOMALY_AGENT] Starting anomaly detection")

    try:
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
                    "max_tokens": 1000,
                },
                timeout=60.0,
            )

        if response.status_code != 200:
            logger.error(
                "[ANOMALY_AGENT] Groq API error %s: %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("Groq returned no completion choices")

        content = choices[0].get("message", {}).get("content")
        if not content:
            raise ValueError("Groq returned empty completion content")

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response is not a JSON object")

        anomalies = _parse_anomalies_payload(parsed)
        logger.info("[ANOMALY_AGENT] Found %d anomalies", len(anomalies))
        return anomalies

    except json.JSONDecodeError as exc:
        logger.exception("[ANOMALY_AGENT] Invalid JSON from LLM")
        raise ValueError("LLM returned invalid JSON") from exc
    except Exception:
        logger.exception("[ANOMALY_AGENT] Anomaly detection failed")
        raise
