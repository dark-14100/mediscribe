"""Rule-based trajectory scoring (PRD §7).

This service is deliberately NOT an LLM call. The four signals are deterministic,
fast, and explainable. Each signal contributes an integer score and (if negative)
a plain-English watch zone string.

Signals
-------
1. Anomaly frequency trend across the last 3 visits.
2. Drift flag trend across the last 3 visits (current in-flight drift overrides
   the most-recent visit's stored drift_flag if that visit was just persisted
   without one).
3. Visit-frequency tightening — gap between the latest two visits vs the average
   gap across the last 4 visits.
4. Symptom recurrence — top-5 keyword overlap across the last 3 subjective
   fields.

Total score mapping
-------------------
    score >= +2  →  direction = "up"      (improving)
    -1 <= score <= +1  →  direction = "stable"
    score <= -2  →  direction = "down"    (declining)

Confidence is ``min(100, (visits_used / 5) * 100)``.

The service returns ``None`` when fewer than 2 visits exist.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.constants import TRAJECTORY_MAX_VISITS
from models.visit import Visit
from schemas.pipeline import DriftFlag, TrajectoryResult

log = logging.getLogger("medscribe.trajectory")


# ---------------------------------------------------------------------------
# Public entry point (called by /analytics/trajectory and the pipeline)
# ---------------------------------------------------------------------------


async def compute(
    patient_id: UUID,
    drift_flag: DriftFlag | None,
    db: AsyncSession,
) -> TrajectoryResult | None:
    """Compute the trajectory for a patient.

    ``drift_flag`` is the (in-memory) drift result from the *current* pipeline
    run. If supplied, it overrides the most-recent visit's stored drift when
    that visit hasn't yet persisted its pipeline output.
    """
    visits = await _load_history(patient_id, db)
    if len(visits) < 2:
        log.info(
            "[trajectory] insufficient history patient_id=%s count=%d",
            patient_id,
            len(visits),
        )
        return None

    recent = visits[-TRAJECTORY_MAX_VISITS:]

    s1, z1 = _signal_anomaly_trend(recent)
    s2, z2 = _signal_drift_trend(recent, drift_flag)
    s3, z3 = _signal_visit_frequency(recent)
    s4, z4 = _signal_symptom_recurrence(recent)

    total = s1 + s2 + s3 + s4
    watch_zones: list[str] = [
        z for z in (z1, z2, z3) if z is not None
    ] + list(z4)

    direction = _score_to_direction(total)
    confidence = min(100, int((len(recent) / TRAJECTORY_MAX_VISITS) * 100))

    log.info(
        "[trajectory] patient_id=%s score=%d direction=%s confidence=%d visits=%d "
        "signals=(anom=%d, drift=%d, freq=%d, sympt=%d)",
        patient_id,
        total,
        direction,
        confidence,
        len(recent),
        s1,
        s2,
        s3,
        s4,
    )

    return TrajectoryResult(
        direction=direction,
        score=float(total),
        confidence=confidence,
        watch_zones=watch_zones,
        computed_from_visits=len(recent),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_history(patient_id: UUID, db: AsyncSession) -> list[Visit]:
    """All visits for a patient, ordered oldest → newest."""
    stmt = (
        select(Visit)
        .where(Visit.patient_id == patient_id)
        .order_by(Visit.visit_date.asc())
    )
    result = await db.scalars(stmt)
    return list(result.all())


def _score_to_direction(score: int) -> str:
    if score >= 2:
        return "up"
    if score <= -2:
        return "down"
    return "stable"


# ---------------------------------------------------------------------------
# Signal 1 — Anomaly frequency trend across the last 3 visits
# ---------------------------------------------------------------------------


def _signal_anomaly_trend(visits: list[Visit]) -> tuple[int, str | None]:
    if len(visits) < 3:
        return 0, None
    last_3 = visits[-3:]
    counts = [len(v.anomalies or []) for v in last_3]
    a, b, c = counts

    if a < b < c:
        return -2, f"Anomaly count increasing 3 visits in a row ({a}→{b}→{c})"
    if a <= b <= c and a != c:
        # Non-decreasing but not strictly increasing — still concerning.
        return -1, f"Anomaly count trending up ({a}→{b}→{c})"
    if a > b > c:
        return 1, None
    return 0, None


# ---------------------------------------------------------------------------
# Signal 2 — Drift flag trend across the last 3 visits
# ---------------------------------------------------------------------------


def _signal_drift_trend(
    visits: list[Visit], current_drift: DriftFlag | None
) -> tuple[int, str | None]:
    if len(visits) < 1:
        return 0, None
    last_3 = visits[-3:]

    def _is_flagged(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(value.get("flagged"))
        if value is None:
            return False
        return bool(getattr(value, "flagged", False))

    flagged: list[bool] = [_is_flagged(v.drift_flag) for v in last_3]

    # Overlay the in-flight drift onto the most-recent visit if its stored value
    # is empty (i.e. pipeline hasn't persisted yet for that visit).
    if current_drift is not None and not flagged[-1] and not last_3[-1].drift_flag:
        flagged[-1] = bool(current_drift.flagged)

    count = sum(flagged)
    if count == 0:
        return 1, None
    if count == 1:
        return 0, None
    return -2, f"Drift flagged in {count} of last {len(flagged)} visits"


# ---------------------------------------------------------------------------
# Signal 3 — Visit-frequency tightening
# ---------------------------------------------------------------------------


def _signal_visit_frequency(visits: list[Visit]) -> tuple[int, str | None]:
    """Latest gap < 70% of the average gap across the last 4 visits → −1."""
    if len(visits) < 4:
        return 0, None
    last_4 = visits[-4:]
    dates = [v.visit_date for v in last_4]
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, 4)]
    if any(g < 0 for g in gaps):
        return 0, None  # data sanity guard
    avg_gap = sum(gaps) / len(gaps)
    latest_gap = gaps[-1]
    if avg_gap > 0 and latest_gap < avg_gap * 0.7:
        return -1, (
            f"Visit frequency increasing (latest gap {latest_gap}d "
            f"vs avg {avg_gap:.1f}d)"
        )
    return 0, None


# ---------------------------------------------------------------------------
# Signal 4 — Symptom recurrence (top-5 keyword overlap across last 3 visits)
# ---------------------------------------------------------------------------


# Generic English stopwords + a small set of clinical-speech filler that we
# never want to count as a "chief complaint" keyword.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "about", "after", "again", "ahead", "alone", "also", "anything",
        "around", "back", "because", "been", "being", "between", "both",
        "could", "didnt", "doing", "doctor", "down", "during", "each",
        "ever", "every", "feels", "feel", "felt", "from", "further",
        "going", "have", "having", "here", "into", "just", "kind", "know",
        "later", "less", "like", "long", "made", "make", "many", "more",
        "most", "much", "must", "need", "needs", "never", "next", "none",
        "nothing", "only", "other", "over", "patient", "people", "please",
        "really", "report", "reports", "right", "said", "same", "seem",
        "seems", "show", "shows", "since", "some", "something", "still",
        "such", "sure", "take", "taken", "takes", "taking", "than", "that",
        "their", "them", "then", "there", "these", "they", "thing", "things",
        "think", "this", "those", "through", "today", "told", "tonight",
        "uses", "very", "want", "wants", "well", "went", "were", "what",
        "when", "where", "which", "while", "with", "without", "would", "year",
        "years", "yesterday", "your",
    }
)


def _extract_top_keywords(text: str, n: int = 5) -> list[str]:
    """Tokenise `text`, drop short/stopword tokens, return the n most frequent."""
    if not text:
        return []
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    filtered = [w for w in words if w not in _STOPWORDS]
    return [w for w, _ in Counter(filtered).most_common(n)]


def _signal_symptom_recurrence(
    visits: list[Visit],
) -> tuple[int, list[str]]:
    if len(visits) < 3:
        return 0, []
    last_3 = visits[-3:]
    top_words_per_visit: list[list[str]] = []
    for v in last_3:
        soap = v.soap_note or {}
        subj = soap.get("subjective", {}) if isinstance(soap, dict) else {}
        subj_text = subj.get("text", "") if isinstance(subj, dict) else ""
        top_words_per_visit.append(_extract_top_keywords(subj_text, n=5))

    if not all(top_words_per_visit):
        return 0, []

    common = set(top_words_per_visit[0])
    for words in top_words_per_visit[1:]:
        common &= set(words)
    if not common:
        return 0, []

    score = -min(len(common), 3)
    zones = [f"Chief complaint recurring: {word}" for word in sorted(common)[:3]]
    return score, zones
