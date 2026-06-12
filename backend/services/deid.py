"""De-identification — strip PHI from text before it reaches an LLM.

We replace identifiers with reversible placeholders (e.g. ``[PATIENT]``,
``[DATE_1]``), keep a private in-memory map so outputs can be re-identified for
the doctor, and persist only a PHI-free *report* (counts, never the map).

Phase A is rules-only and deterministic (no LLM, no extra dependencies):

1. **Known-entity scrub** — the patient record gives us the exact truth
   (``full_name`` and its tokens, ``dob``); these are the highest-precision
   replacements because they're real data, not guesses.
2. **Regex scrub** — universal identifier patterns (email, URL, SSN, phone,
   dates, MRN/long-digit IDs).

Re-identification (`reidentify`) is exact-substring and **safe by construction**:
the only thing it can ever write back is what we removed, so a placeholder the
LLM mangled simply survives as a harmless ``[DATE_1]`` rather than leaking PHI.

Scope: this covers *text* sent to the reasoning LLMs (transcript, injected
history). The ASR audio itself still reaches Whisper and stays governed by the
Groq BAA — see DEID_SPEC.md §4.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from core.config import settings
from schemas.pipeline import DeidReport, TranscriptLine

logger = logging.getLogger("medscribe.deid")

# Regex families, applied in this order. Order matters: remove structured
# identifiers (email, ssn, dates) before the greedy long-digit/phone patterns so
# they don't get mislabeled. Each already-replaced span becomes a bracketed
# placeholder that later patterns won't match.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_MRN_RE = re.compile(r"\bMRN[:#]?\s?[A-Za-z0-9-]+\b", re.IGNORECASE)
_DATE_NUM_RE = re.compile(
    r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:\d{2}|\d{4})\b"
)
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_DATE_WORD_RE = re.compile(
    rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"
)
_LONG_ID_RE = re.compile(r"\b\d{6,}\b")

_PLACEHOLDER_RE = re.compile(r"\[[A-Z]+(?:_\d+)?\]")


class _Deidentifier:
    def __init__(self, patient: Any = None) -> None:
        self.mapping: dict[str, str] = {}          # placeholder -> original
        self._seen: dict[tuple[str, str], str] = {}  # (category, lower) -> placeholder
        self._family_counts: dict[str, int] = defaultdict(int)
        self.counts: dict[str, int] = defaultdict(int)  # category -> occurrences
        self._full_name_low = ""
        self._known = self._build_known(patient)

    # -- setup -------------------------------------------------------------
    def _build_known(self, patient: Any) -> list[tuple[re.Pattern[str], str, str]]:
        items: list[tuple[str, str]] = []
        if patient is not None:
            name = getattr(patient, "full_name", None)
            if name:
                self._full_name_low = str(name).strip().lower()
                items.append((str(name).strip(), "name"))
                for tok in re.split(r"\s+", str(name).strip()):
                    if len(tok) >= 2:
                        items.append((tok, "name"))
            dob = getattr(patient, "dob", None)
            if dob:
                items.append((str(dob), "dob"))

        compiled: list[tuple[re.Pattern[str], str, str]] = []
        seen_text: set[str] = set()
        # Longest first so a full name is replaced before its individual tokens.
        for text, cat in sorted(items, key=lambda x: len(x[0]), reverse=True):
            low = text.lower()
            if low in seen_text:
                continue
            seen_text.add(low)
            compiled.append(
                (re.compile(rf"\b{re.escape(text)}\b", re.IGNORECASE), cat, text)
            )
        return compiled

    # -- placeholder bookkeeping -------------------------------------------
    def _placeholder(self, category: str, original: str, fixed: str | None = None) -> str:
        key = (category, original.lower())
        self.counts[category] += 1
        if key in self._seen:
            return self._seen[key]
        if fixed is not None:
            placeholder = fixed
        else:
            self._family_counts[category] += 1
            placeholder = f"[{category.upper()}_{self._family_counts[category]}]"
        self._seen[key] = placeholder
        self.mapping[placeholder] = original
        return placeholder

    # -- scrubbing ---------------------------------------------------------
    def scrub(self, text: str) -> str:
        if not text:
            return text

        # Structured identifiers first — an email/URL can *contain* a name, so
        # protect them before the known-name pass (which matches name tokens on
        # word boundaries and would otherwise fire inside "jane@example.com").
        text = self._scrub_regex(text, _EMAIL_RE, "email")
        text = self._scrub_regex(text, _URL_RE, "url")
        text = self._scrub_regex(text, _SSN_RE, "id")
        text = self._scrub_regex(text, _MRN_RE, "id")

        for rx, cat, original in self._known:
            fixed = (
                "[PATIENT]"
                if cat == "name" and original.lower() == self._full_name_low
                else "[DOB]"
                if cat == "dob"
                else None
            )
            text = rx.sub(
                lambda _m, c=cat, o=original, f=fixed: self._placeholder(c, o, f), text
            )

        if settings.DEID_REDACT_DATES:
            text = self._scrub_regex(text, _DATE_NUM_RE, "date")
            text = self._scrub_regex(text, _DATE_WORD_RE, "date")
        text = self._scrub_regex(text, _PHONE_RE, "phone")
        text = self._scrub_regex(text, _LONG_ID_RE, "id")
        return text

    def _scrub_regex(self, text: str, rx: re.Pattern[str], category: str) -> str:
        return rx.sub(lambda m: self._placeholder(category, m.group(0)), text)

    # -- output ------------------------------------------------------------
    def report(self, method: str = "rules") -> DeidReport:
        return DeidReport(
            applied=True,
            method=method,  # type: ignore[arg-type]
            entity_count=sum(self.counts.values()),
            by_category=dict(self.counts),
        )


class DeidResult:
    """Outcome of de-identifying a transcript, plus tools to continue scrubbing
    additional text (e.g. injected history) with the same reversible map."""

    def __init__(self, deidentifier: _Deidentifier, transcript: list[TranscriptLine]):
        self._d = deidentifier
        self.transcript = transcript

    @property
    def mapping(self) -> dict[str, str]:
        return self._d.mapping

    def scrub_text(self, text: str) -> str:
        return self._d.scrub(text or "")

    def report(self) -> DeidReport:
        return self._d.report()


def deidentify_transcript(transcript: list[Any], patient: Any = None) -> DeidResult:
    """Return a de-identified copy of the transcript (PHI replaced) + a map."""
    deidentifier = _Deidentifier(patient)
    clean: list[TranscriptLine] = []
    for entry in transcript or []:
        data = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
        data["text"] = deidentifier.scrub(str(data.get("text", "")))
        clean.append(TranscriptLine.model_validate(data))
    logger.info(
        "[DEID] entities=%d categories=%s",
        sum(deidentifier.counts.values()),
        dict(deidentifier.counts),
    )
    return DeidResult(deidentifier, clean)


def reidentify(obj: Any, mapping: dict[str, str]) -> Any:
    """Deep-walk a JSON-safe structure and restore originals from placeholders."""
    if not mapping:
        return obj
    keys = sorted(mapping, key=len, reverse=True)  # longest first: [ID_10] before [ID_1]

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            for placeholder in keys:
                if placeholder in value:
                    value = value.replace(placeholder, mapping[placeholder])
            return value
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    return walk(obj)


def count_residual(obj: Any, mapping: dict[str, str]) -> int:
    """Count placeholders that survived re-identification (should be 0)."""
    if not mapping:
        return 0
    blob = json.dumps(obj, default=str)
    return sum(blob.count(placeholder) for placeholder in mapping)
