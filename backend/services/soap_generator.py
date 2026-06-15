from __future__ import annotations

import json
import logging
from typing import Any

from core.note_templates import get_template, normalize_note_type, section_keys
from services.groq_retry import chat_completion

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"
SOAP_KEYS = ("subjective", "objective", "assessment", "plan")

SYSTEM_PROMPT = """You are a medical documentation AI. Given a doctor-patient conversation transcript, generate a SOAP note in JSON format.

Return ONLY a JSON object with exactly these four keys: subjective, objective, assessment, plan.

Each key must have:
- "text": a concise clinical summary for that section
- "source_lines": list of line numbers from the transcript that support this section

Rules:
- Only use information present in the transcript. Never invent clinical details.
- Be concise and clinical in language.
- If a section has no supporting information, set text to empty string and source_lines to empty list.
- Return valid JSON only. No explanation, no markdown, no extra keys."""

EMPTY_SOAP_FIELD: dict[str, str | list[int]] = {"text": "", "source_lines": []}


def _transcript_entry_dict(entry: Any) -> dict[str, Any]:
    """Accept dicts or Pydantic ``TranscriptLine`` models from the pipeline API."""
    if hasattr(entry, "model_dump"):
        return entry.model_dump()
    if isinstance(entry, dict):
        return entry
    return {"line_index": "?", "speaker": "unknown", "text": str(entry)}


def _format_transcript_for_prompt(transcript: list[Any]) -> str:
    lines: list[str] = []
    for entry in transcript:
        data = _transcript_entry_dict(entry)
        line_num = data.get("line", data.get("line_index", "?"))
        speaker = data.get("speaker", "unknown")
        text = data.get("text", "")
        lines.append(f"Line {line_num} [{speaker}]: {text}")
    return "\n".join(lines)


def _normalize_soap_field(value: Any) -> dict[str, str | list[int]]:
    if not isinstance(value, dict):
        return dict(EMPTY_SOAP_FIELD)

    text = value.get("text", "")
    if not isinstance(text, str):
        text = str(text) if text is not None else ""

    raw_lines = value.get("source_lines", [])
    source_lines: list[int] = []
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                source_lines.append(int(item))

    return {"text": text, "source_lines": source_lines}


def _validate_and_normalize_soap(payload: dict[str, Any]) -> dict[str, dict[str, str | list[int]]]:
    return {key: _normalize_soap_field(payload.get(key)) for key in SOAP_KEYS}


def _parse_llm_content(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM response is not a JSON object")
    return parsed


async def generate_soap(transcript: list[Any]) -> dict:
    logger.info("[SOAP_GENERATOR] Starting SOAP generation")
    try:
        user_message = _format_transcript_for_prompt(transcript)

        data = await chat_completion(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            max_tokens=1000,
            label="soap_generator",
        )
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("Groq returned no completion choices")

        content = choices[0].get("message", {}).get("content")
        if not content:
            raise ValueError("Groq returned empty completion content")

        parsed = _parse_llm_content(content)
        soap = _validate_and_normalize_soap(parsed)

        logger.info("[SOAP_GENERATOR] SOAP generation successful")
        return soap

    except Exception:
        logger.exception("[SOAP_GENERATOR] SOAP generation failed")
        raise


def _build_note_prompt(note_type: str) -> str:
    """System prompt for a non-SOAP note type, built from its template."""
    template = get_template(note_type)
    keys = section_keys(note_type)
    guidance = template.get("guidance", {})
    lines = "\n".join(
        f'- "{key}": {guidance.get(key, "the relevant content for this section")}'
        for key in keys
    )
    key_list = ", ".join(keys)
    return (
        f"You are a medical documentation AI. Given a doctor-patient conversation "
        f"transcript, generate a {template['label']} in JSON format.\n\n"
        f"Return ONLY a JSON object with exactly these keys: {key_list}.\n\n"
        f"Each key must have:\n"
        f'- "text": a concise clinical summary for that section\n'
        f'- "source_lines": list of line numbers from the transcript that support it\n\n'
        f"Sections:\n{lines}\n\n"
        f"Rules:\n"
        f"- Only use information present in the transcript. Never invent details.\n"
        f"- Be concise and clinical.\n"
        f"- If a section has no supporting information, set text to empty string "
        f"and source_lines to empty list.\n"
        f"- Return valid JSON only. No explanation, no markdown, no extra keys."
    )


async def generate_note(transcript: list[Any], note_type: str = "soap") -> dict:
    """Generate a clinical note of the given type.

    Returns a flat ``{section_key: {text, source_lines}}`` dict. For ``soap`` this
    delegates to ``generate_soap`` so the SOAP path is byte-for-byte unchanged.
    """
    note_type = normalize_note_type(note_type)
    if note_type == "soap":
        return await generate_soap(transcript)

    keys = section_keys(note_type)
    logger.info("[SOAP_GENERATOR] Starting %s generation", note_type)
    try:
        data = await chat_completion(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": _build_note_prompt(note_type)},
                {"role": "user", "content": _format_transcript_for_prompt(transcript)},
            ],
            response_format={"type": "json_object"},
            max_tokens=1400,
            label=f"note_generator:{note_type}",
        )
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("Groq returned no completion choices")
        content = choices[0].get("message", {}).get("content")
        if not content:
            raise ValueError("Groq returned empty completion content")

        parsed = _parse_llm_content(content)
        note = {key: _normalize_soap_field(parsed.get(key)) for key in keys}
        logger.info("[SOAP_GENERATOR] %s generation successful", note_type)
        return note
    except Exception:
        logger.exception("[SOAP_GENERATOR] %s generation failed", note_type)
        raise
