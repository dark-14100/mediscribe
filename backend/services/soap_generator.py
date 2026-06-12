from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from core.config import settings
from services.groq_retry import call_with_retries

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
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


async def _request_soap_completion(user_message: str) -> httpx.Response:
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
            timeout=settings.GROQ_TIMEOUT_SECONDS,
        )

    if response.status_code != 200:
        logger.error(
            "[SOAP_GENERATOR] Groq API error %s: %s",
            response.status_code,
            response.text,
        )
        response.raise_for_status()
    return response


async def generate_soap(transcript: list[Any]) -> dict:
    logger.info("[SOAP_GENERATOR] Starting SOAP generation")
    try:
        user_message = _format_transcript_for_prompt(transcript)

        response = await call_with_retries(
            lambda: _request_soap_completion(user_message),
            label="soap_generator",
        )

        data = response.json()
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
