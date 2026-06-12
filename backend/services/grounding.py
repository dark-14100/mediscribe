"""Grounding gate — verify each SOAP claim is supported by the transcript.

This is a *faithfulness* check, not a clinical-correctness check: it confirms
the note didn't invent statements the conversation never contained. It does NOT
judge whether the diagnosis is right (that's the differential/compliance/anomaly
agents' job).

Phase A is rules-only and deterministic (no LLM, no extra dependencies):

1. Citation presence — non-empty text must cite at least one transcript line.
2. Citation validity — every cited number must be a real transcript line_index.
3. Lexical overlap — the claim's content words must actually appear in its cited
   lines. This catches the model citing lines that don't support the claim.

A later phase can add an opt-in LLM verifier (settings.GROUNDING_USE_LLM) that
can only *downgrade* a rules "grounded" result, never rubber-stamp it.
"""
from __future__ import annotations

import logging
import re
from typing import Any

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


def _grade_field(key: str, field: dict[str, Any], line_map: dict[int, str]) -> GroundingFieldResult:
    text = field["text"].strip()
    source_lines = field["source_lines"]

    # Empty section is neutral — nothing to verify, don't penalise it.
    if not text:
        return GroundingFieldResult(
            field=key, status="grounded", confidence=1.0, cited_lines_valid=True
        )

    valid_lines = [n for n in source_lines if n in line_map]
    cited_lines_valid = bool(source_lines) and len(valid_lines) == len(source_lines)
    cited_tokens: set[str] = set()
    for n in valid_lines:
        cited_tokens |= _content_tokens(line_map[n])

    claims: list[GroundingClaim] = []
    confidences: list[float] = []
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

        confidences.append(score)
        if status != "grounded":
            claims.append(
                GroundingClaim(
                    field=key,
                    text=sentence,
                    status=status,
                    confidence=round(score, 3),
                    cited_lines=source_lines,
                    issue=issue,
                )
            )

    field_status = min(
        (c.status for c in claims), key=lambda s: _STATUS_RANK[s], default="grounded"
    )
    field_confidence = sum(confidences) / len(confidences) if confidences else 1.0

    return GroundingFieldResult(
        field=key,
        status=field_status,
        confidence=round(field_confidence, 3),
        cited_lines_valid=cited_lines_valid,
        unsupported_claims=claims,
    )


async def verify(soap_note: Any, transcript: list[Any]) -> GroundingResult:
    """Return a grounding verdict for a SOAP note against its transcript.

    Async so a future LLM verifier can slot in without changing the signature;
    the rules-only path does no awaiting.
    """
    line_map = _transcript_line_map(transcript or [])
    fields = [_grade_field(key, _soap_field(soap_note, key), line_map) for key in SOAP_KEYS]

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
        checked_with="rules",
    )
