"""Grounding gate — verify each SOAP claim is supported by the transcript.

This is a *faithfulness* check, not a clinical-correctness check: it confirms
the note didn't invent statements the conversation never contained. It does NOT
judge whether the diagnosis is right (that's the differential/compliance/anomaly
agents' job).

Layer 1 (always on) is rules-only and deterministic (no LLM, no extra deps):

1. Citation presence — non-empty text must cite at least one transcript line.
2. Citation validity — every cited number must be a real transcript line_index.
3. Lexical overlap — the claim's content words must actually appear in its cited
   lines. This catches the model citing lines that don't support the claim.

Layer 2 (Phase B, opt-in via settings.GROUNDING_USE_LLM) adds an LLM verifier
scoped to GROUNDING_LLM_FIELDS (Assessment/Plan by default). It judges *meaning*
rather than word overlap, can only *downgrade* a verdict (never rubber-stamp),
and falls back to the Layer-1 result on any error — so the gate is never a single
point of failure. Groq is imported lazily so the rules path stays dependency-light.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from core.config import settings
from schemas.pipeline import (
    GroundingClaim,
    GroundingFieldResult,
    GroundingResult,
    GroundingStatus,
)

logger = logging.getLogger("medscribe.grounding")

SOAP_KEYS: tuple[str, ...] = ("subjective", "objective", "assessment", "plan")

# Fields weighted higher in the overall score: a fabricated Assessment/Plan is
# far more dangerous than an over-summarised Subjective.
_FIELD_WEIGHTS: dict[str, float] = {
    "subjective": 1.0,
    "objective": 1.0,
    "assessment": 2.0,
    "plan": 2.0,
}

_STATUS_RANK: dict[str, int] = {"ungrounded": 0, "partial": 1, "grounded": 2}

# --- Layer 2 (optional LLM verifier) ---------------------------------------
# Map the model's verdict vocabulary to our statuses, and a confidence proxy for
# a downgraded claim (we have no real probability from the model).
_VERDICT_MAP: dict[str, GroundingStatus] = {
    "SUPPORTED": "grounded",
    "PARTIAL": "partial",
    "NOT_SUPPORTED": "ungrounded",
}
_LLM_CONF_PROXY: dict[str, float] = {"grounded": 0.9, "partial": 0.5, "ungrounded": 0.1}

_LLM_SYSTEM = (
    "You verify faithfulness, NOT clinical correctness. For each claim, decide "
    "whether the cited transcript lines support it. Output ONLY a JSON object of "
    'the form {"verdicts": [{"id": <int>, "verdict": "SUPPORTED|PARTIAL|'
    'NOT_SUPPORTED", "reason": "<short>"}]}. SUPPORTED = the claim is fully '
    "stated or directly entailed by the cited lines; PARTIAL = related but not "
    "fully supported; NOT_SUPPORTED = not derivable from the cited lines. Judge "
    "only against the provided lines. Bracketed tokens like [PATIENT] are "
    "redacted identifiers; treat them as opaque placeholders."
)

# Small stopword list — we only want *content* words to count toward overlap.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
        "with", "without", "is", "are", "was", "were", "be", "been", "being", "as",
        "at", "by", "from", "this", "that", "these", "those", "it", "its", "his",
        "her", "their", "they", "he", "she", "i", "we", "you", "patient", "denies",
        "reports", "no", "not", "has", "have", "had", "will", "would", "should",
        "than", "then", "there", "here", "also", "some", "any", "per", "due",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def _as_dict(entry: Any) -> dict[str, Any]:
    if hasattr(entry, "model_dump"):
        return entry.model_dump()
    if isinstance(entry, dict):
        return entry
    return {}


def _content_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in _WORD_RE.findall((text or "").lower())
        if tok not in _STOPWORDS and len(tok) >= 2
    }


def _split_sentences(text: str) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_RE.findall(text or "")]
    return [s for s in sentences if s]


def _transcript_line_map(transcript: list[Any]) -> dict[int, str]:
    """Map line_index -> line text, tolerating dicts or TranscriptLine models."""
    lines: dict[int, str] = {}
    for entry in transcript:
        data = _as_dict(entry)
        idx = data.get("line_index", data.get("line"))
        if isinstance(idx, bool) or not isinstance(idx, (int, float)):
            continue
        lines[int(idx)] = str(data.get("text", ""))
    return lines


def _soap_field(soap: Any, key: str) -> dict[str, Any]:
    """Extract {text, source_lines} for a field from a SOAPNote model or dict."""
    container = soap.model_dump() if hasattr(soap, "model_dump") else soap
    field = (container or {}).get(key) if isinstance(container, dict) else None
    if not isinstance(field, dict):
        return {"text": "", "source_lines": []}
    raw_lines = field.get("source_lines", [])
    source_lines = [
        int(n)
        for n in (raw_lines if isinstance(raw_lines, list) else [])
        if isinstance(n, (int, float)) and not isinstance(n, bool)
    ]
    return {"text": str(field.get("text", "") or ""), "source_lines": source_lines}


def _score_to_status(score: float) -> GroundingStatus:
    if score >= settings.GROUNDING_GROUNDED_THRESHOLD:
        return "grounded"
    if score >= settings.GROUNDING_PARTIAL_THRESHOLD:
        return "partial"
    return "ungrounded"


def _field_result_from_claims(
    key: str, all_claims: list[GroundingClaim], cited_lines_valid: bool
) -> GroundingFieldResult:
    """Roll a field's per-sentence claims up into a field-level verdict."""
    if not all_claims:
        return GroundingFieldResult(
            field=key, status="grounded", confidence=1.0, cited_lines_valid=cited_lines_valid
        )
    field_status = min(
        (c.status for c in all_claims), key=lambda s: _STATUS_RANK[s]
    )
    field_confidence = sum(c.confidence for c in all_claims) / len(all_claims)
    return GroundingFieldResult(
        field=key,
        status=field_status,
        confidence=round(field_confidence, 3),
        cited_lines_valid=cited_lines_valid,
        unsupported_claims=[c for c in all_claims if c.status != "grounded"],
    )


def _grade_field(
    key: str, field: dict[str, Any], line_map: dict[int, str]
) -> tuple[GroundingFieldResult, list[GroundingClaim]]:
    """Rules grading. Returns the field result AND every sentence as a claim
    (grounded ones included) so the optional LLM layer can re-check them."""
    text = field["text"].strip()
    source_lines = field["source_lines"]

    # Empty section is neutral — nothing to verify, don't penalise it.
    if not text:
        return (
            GroundingFieldResult(
                field=key, status="grounded", confidence=1.0, cited_lines_valid=True
            ),
            [],
        )

    valid_lines = [n for n in source_lines if n in line_map]
    cited_lines_valid = bool(source_lines) and len(valid_lines) == len(source_lines)
    cited_tokens: set[str] = set()
    for n in valid_lines:
        cited_tokens |= _content_tokens(line_map[n])

    all_claims: list[GroundingClaim] = []
    for sentence in _split_sentences(text):
        claim_tokens = _content_tokens(sentence)

        if not source_lines:
            status: GroundingStatus = "ungrounded"
            score = 0.0
            issue: str | None = "No cited transcript lines."
        elif not valid_lines:
            status = "ungrounded"
            score = 0.0
            issue = "Citations point to lines not in the transcript."
        elif not claim_tokens:
            # Nothing substantive to verify (e.g. boilerplate) — treat as supported.
            status = "grounded"
            score = 1.0
            issue = None
        else:
            score = len(claim_tokens & cited_tokens) / len(claim_tokens)
            status = _score_to_status(score)
            issue = (
                None
                if status == "grounded"
                else "Cited lines don't fully support this statement."
            )

        all_claims.append(
            GroundingClaim(
                field=key,
                text=sentence,
                status=status,
                confidence=round(score, 3),
                cited_lines=source_lines,
                issue=issue,
            )
        )

    return _field_result_from_claims(key, all_claims, cited_lines_valid), all_claims


def _llm_field_set() -> set[str]:
    """Fields eligible for the LLM second pass (config-driven)."""
    raw = settings.GROUNDING_LLM_FIELDS or ""
    requested = {f.strip().lower() for f in raw.split(",") if f.strip()}
    return requested & set(SOAP_KEYS)


async def _llm_verify_field(
    key: str, all_claims: list[GroundingClaim], line_map: dict[int, str]
) -> dict[int, tuple[GroundingStatus, str | None]]:
    """Ask the LLM to judge the field's grounded/partial claims against their
    cited lines. Returns {claim_index: (status, reason)}. Raises on transport
    errors so the caller can fall back to the rules result."""
    eligible = [
        (i, c) for i, c in enumerate(all_claims) if c.status in ("grounded", "partial")
    ]
    if not eligible:
        return {}

    items = [
        {
            "id": i,
            "claim": c.text,
            "cited_lines": [
                {"line": n, "text": line_map[n]} for n in c.cited_lines if n in line_map
            ],
        }
        for i, c in eligible
    ]

    # Import here (not at module load) so the rules-only path — and the eval
    # harness's minimal-deps environment — never has to import httpx.
    from services.groq_retry import chat_completion

    response = await chat_completion(
        model=settings.GROUNDING_MODEL,
        messages=[
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": json.dumps({"field": key, "claims": items})},
        ],
        label="grounding_verify",
        max_tokens=600,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = response["choices"][0]["message"]["content"]
    data = json.loads(content)

    verdicts: dict[int, tuple[GroundingStatus, str | None]] = {}
    for entry in data.get("verdicts", []):
        cid = entry.get("id")
        status = _VERDICT_MAP.get(str(entry.get("verdict", "")).strip().upper())
        if isinstance(cid, int) and not isinstance(cid, bool) and status is not None:
            reason = str(entry.get("reason", "")).strip() or None
            verdicts[cid] = (status, reason)
    return verdicts


def _merge_claims(
    all_claims: list[GroundingClaim],
    verdicts: dict[int, tuple[GroundingStatus, str | None]],
) -> list[GroundingClaim]:
    """Apply the downgrade-only rule: the LLM may tighten a claim, never relax it."""
    merged: list[GroundingClaim] = []
    for i, claim in enumerate(all_claims):
        verdict = verdicts.get(i)
        if verdict is None:
            merged.append(claim)
            continue
        llm_status, reason = verdict
        final_status = min(
            (claim.status, llm_status), key=lambda s: _STATUS_RANK[s]
        )
        if final_status == claim.status:
            merged.append(claim)  # LLM agreed or was more lenient — keep rules.
            continue
        merged.append(
            GroundingClaim(
                field=claim.field,
                text=claim.text,
                status=final_status,
                confidence=round(min(claim.confidence, _LLM_CONF_PROXY[llm_status]), 3),
                cited_lines=claim.cited_lines,
                issue=reason
                or "LLM verifier judged the cited lines do not fully support this statement.",
            )
        )
    return merged


async def verify(soap_note: Any, transcript: list[Any]) -> GroundingResult:
    """Return a grounding verdict for a SOAP note against its transcript.

    Layer 1 (rules) always runs. Layer 2 (LLM) runs only when
    ``GROUNDING_USE_LLM`` is set, is scoped to ``GROUNDING_LLM_FIELDS``, can only
    *downgrade* a verdict, and degrades to the rules result on any error.
    """
    line_map = _transcript_line_map(transcript or [])
    graded = {
        key: _grade_field(key, _soap_field(soap_note, key), line_map)
        for key in SOAP_KEYS
    }

    checked_with: Literal["rules", "rules+llm"] = "rules"
    if settings.GROUNDING_USE_LLM:
        llm_fields = _llm_field_set()
        for key in SOAP_KEYS:
            field_result, all_claims = graded[key]
            if key not in llm_fields or not all_claims:
                continue
            try:
                verdicts = await _llm_verify_field(key, all_claims, line_map)
            except Exception:  # noqa: BLE001 — verifier must never break the gate
                logger.exception(
                    "[GROUNDING] LLM verify failed for %s — keeping rules result", key
                )
                continue
            if not verdicts:
                continue
            merged = _merge_claims(all_claims, verdicts)
            graded[key] = (
                _field_result_from_claims(key, merged, field_result.cited_lines_valid),
                merged,
            )
            checked_with = "rules+llm"

    fields = [graded[key][0] for key in SOAP_KEYS]

    # Overall score weights non-empty fields; an empty note is trivially grounded.
    scored = [
        (f, _FIELD_WEIGHTS.get(f.field, 1.0))
        for f in fields
        if not (f.status == "grounded" and not f.unsupported_claims and f.confidence == 1.0)
    ]
    if scored:
        total_weight = sum(w for _, w in scored)
        overall_confidence = sum(f.confidence * w for f, w in scored) / total_weight
        overall_status = min(
            (f.status for f, _ in scored), key=lambda s: _STATUS_RANK[s]
        )
    else:
        overall_confidence = 1.0
        overall_status = "grounded"

    logger.info(
        "[GROUNDING] status=%s confidence=%.2f flagged_fields=%d",
        overall_status,
        overall_confidence,
        sum(1 for f in fields if f.unsupported_claims),
    )

    return GroundingResult(
        status=overall_status,
        confidence=round(overall_confidence, 3),
        fields=fields,
        checked_with=checked_with,
    )
