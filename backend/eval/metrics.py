"""Scoring metrics for the evaluation harness.

All text metrics are dependency-free and deterministic. The two trust metrics
(hallucination, PHI leak) reuse the production services directly so the harness
measures *exactly* what ships, not a re-implementation.

Conventions for every score: 0.0–1.0, two empty inputs => 1.0 (trivially equal),
exactly one empty input => 0.0.
"""
from __future__ import annotations

import re
from typing import Any

# Shared tokenizer: lowercase alphanumeric runs. Mirrors the grounding gate's
# notion of a "word" so quality and hallucination scoring stay consistent.
_WORD_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


# --- Quality -------------------------------------------------------------


def token_f1(pred: str, ref: str) -> float:
    """Set-overlap F1 of word tokens between prediction and reference."""
    pred_set = set(_tokens(pred))
    ref_set = set(_tokens(ref))
    if not pred_set and not ref_set:
        return 1.0
    if not pred_set or not ref_set:
        return 0.0
    overlap = len(pred_set & ref_set)
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_set)
    recall = overlap / len(ref_set)
    return 2 * precision * recall / (precision + recall)


def _lcs_length(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for token_a in a:
        curr = [0]
        for j, token_b in enumerate(b, start=1):
            if token_a == token_b:
                curr.append(prev[j - 1] + 1)
            else:
                curr.append(max(prev[j], curr[j - 1]))
        prev = curr
    return prev[-1]


def rouge_l(pred: str, ref: str) -> float:
    """ROUGE-L F-measure: longest-common-subsequence over word tokens."""
    pred_tokens = _tokens(pred)
    ref_tokens = _tokens(ref)
    if not pred_tokens and not ref_tokens:
        return 1.0
    if not pred_tokens or not ref_tokens:
        return 0.0
    lcs = _lcs_length(pred_tokens, ref_tokens)
    if lcs == 0:
        return 0.0
    precision = lcs / len(pred_tokens)
    recall = lcs / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def semantic_sim(pred: str, ref: str) -> float:
    """Cosine similarity of embeddings (opt-in; loads the embedding model).

    Imported lazily so the harness never pays the model-load cost unless
    ``--semantic`` is requested.
    """
    if not (pred or "").strip() and not (ref or "").strip():
        return 1.0
    if not (pred or "").strip() or not (ref or "").strip():
        return 0.0
    from services.embedding import embed_text  # local import: heavy dependency

    a = embed_text(pred)
    b = embed_text(ref)
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    cosine = dot / (norm_a * norm_b)
    # Clamp into [0, 1]: negatives mean "unrelated" for our purposes.
    return max(0.0, min(1.0, cosine))


# --- Trust ---------------------------------------------------------------


def _count_sentences(soap: dict[str, Any]) -> int:
    """Total verifiable sentences across SOAP fields (matches grounding's split)."""
    total = 0
    for key in ("subjective", "objective", "assessment", "plan"):
        field = soap.get(key) or {}
        text = str(field.get("text", "") or "")
        total += sum(1 for s in _SENTENCE_RE.findall(text) if s.strip())
    return total


async def hallucination_rate(soap: dict[str, Any], transcript: list[Any]) -> float:
    """Fraction of SOAP sentences the grounding gate flags as unsupported.

    Runs the real grounding verifier so the harness number tracks production.
    """
    from services import grounding  # local import: pulls in config/schemas

    total = _count_sentences(soap)
    if total == 0:
        return 0.0
    result = await grounding.verify(soap, transcript)
    unsupported = sum(len(f.unsupported_claims) for f in result.fields)
    return min(1.0, unsupported / total)


def phi_leak_rate(
    transcript: list[Any], patient: Any, planted: list[str]
) -> float:
    """Fraction of planted identifiers that survive de-identification.

    MUST be 0. A non-zero value means PHI reached (or would reach) the LLM.
    """
    if not planted:
        return 0.0
    from services.deid import deidentify_transcript  # local import

    result = deidentify_transcript(transcript, patient)
    clean_blob = " ".join((line.text or "") for line in result.transcript).lower()
    leaked = sum(1 for ident in planted if ident and ident.lower() in clean_blob)
    return leaked / len(planted)
