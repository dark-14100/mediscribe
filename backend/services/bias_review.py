"""Bias review service — Phase 6.

Scans a SOAP note for language that may reflect implicit gender, age, or
socioeconomic bias. Returns a list of BiasFlag objects, each with the
offending phrase, bias category, and a suggested neutral rewrite.

The pipeline route calls this as:
    from services.bias_review import review
    bias_flags = await review(soap_note)
"""
from __future__ import annotations

import json
import logging

import httpx

from core.config import settings
from schemas.pipeline import BiasFlag, SOAPNote
from services.groq_retry import call_with_retries

log = logging.getLogger("medscribe.bias_review")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

VALID_BIAS_TYPES = frozenset({"gender_bias", "age_bias", "socioeconomic_bias"})

SYSTEM_PROMPT = """\
You are a clinical language bias reviewer. You will be given a SOAP note from \
a primary care visit.

Identify any phrases or sentences in the note that may reflect implicit bias \
in exactly these categories:
- gender_bias: language that makes unwarranted assumptions based on the \
patient's gender or uses gendered stereotypes (e.g. "hysterical", \
"drug-seeking female", "overly emotional").
- age_bias: language that dismisses or over-attributes symptoms to age \
(e.g. "typical for someone his age", "elderly complaints", \
"just getting old").
- socioeconomic_bias: language that makes assumptions based on perceived \
income, insurance status, or lifestyle (e.g. "non-compliant as expected", \
"probably can't afford", "low-income patient likely").

Return ONLY a JSON object with a single key "bias_flags" whose value is an \
array. Each item must have exactly these three fields:
- "phrase": the exact offending substring from the note (max 10 words)
- "type": one of "gender_bias", "age_bias", "socioeconomic_bias"
- "suggested_rewrite": a concise, neutral alternative phrasing (max 15 words)

Return an empty array if no bias is detected. Do not flag standard clinical \
terminology or neutral symptom descriptions.\
"""


def _build_user_message(soap_note: SOAPNote) -> str:
    return (
        f"SOAP NOTE:\n"
        f"Subjective: {soap_note.subjective.text}\n"
        f"Objective: {soap_note.objective.text}\n"
        f"Assessment: {soap_note.assessment.text}\n"
        f"Plan: {soap_note.plan.text}\n"
    )


def _parse_flags(raw: list) -> list[BiasFlag]:
    flags: list[BiasFlag] = []
    for item in raw:
        try:
            bias_type = item.get("type")
            if bias_type not in VALID_BIAS_TYPES:
                log.debug("[bias_review] skipping item with unknown type=%r", bias_type)
                continue
            flags.append(
                BiasFlag(
                    phrase=str(item["phrase"]),
                    type=bias_type,
                    suggested_rewrite=str(item["suggested_rewrite"]),
                )
            )
        except Exception:  # noqa: BLE001
            log.debug("[bias_review] skipping malformed flag item: %r", item)
    return flags


async def review(soap_note: SOAPNote) -> list[BiasFlag]:
    """Call Groq to identify bias flags in the SOAP note.

    Returns an empty list when the note is clean. Never raises on a
    malformed LLM response — bad items are silently skipped.
    Raises httpx.HTTPStatusError if the Groq API request fails.
    """
    user_message = _build_user_message(soap_note)
    log.info("[bias_review] sending SOAP note for bias review")

    async def _request() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GROQ_URL,
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
                    "max_tokens": 600,
                },
                timeout=settings.GROQ_TIMEOUT_SECONDS,
            )
        if response.status_code != 200:
            log.error(
                "[bias_review] Groq API error %s: %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()
        return response

    response = await call_with_retries(_request, label="bias_review")

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        log.warning("[bias_review] Groq returned no choices — returning empty list")
        return []

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        log.warning("[bias_review] Groq returned empty content — returning empty list")
        return []

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        log.warning("[bias_review] Groq returned invalid JSON — returning empty list")
        return []

    raw_flags = parsed.get("bias_flags", [])
    if not isinstance(raw_flags, list):
        log.warning("[bias_review] 'bias_flags' is not a list — returning empty list")
        return []

    flags = _parse_flags(raw_flags)
    log.info("[bias_review] detected %d bias flag(s)", len(flags))
    return flags
