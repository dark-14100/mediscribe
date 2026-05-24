"""Unit tests for services/drift_agent.py.

All embedding computation and DB queries are mocked so no real model or
database is needed. Tests cover:
  - Drift detected: high cosine distance → flagged=True.
  - No drift: low cosine distance → flagged=False, direction="no_significant_drift".
  - Insufficient history: fewer than 2 prior embeddings → returns None.
  - No patient speech in transcript → returns None.
  - Direction labeling: pain keywords → increased_pain_descriptors.
  - Direction labeling: negative-affect keywords → increased_negative_affect.
  - Direction labeling: no keywords when flagged → increased_negative_affect fallback.
  - delta and threshold are set correctly on the returned flag.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import numpy as np
import pytest

from schemas.pipeline import TranscriptLine
from services.drift_agent import (
    _determine_direction,
    _extract_patient_speech,
    detect,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_PATIENT_ID = uuid.uuid4()

# Unit vector pointing in +x direction (dim 0 = 1.0, rest 0.0)
_VEC_A = [1.0] + [0.0] * 383
# Nearly identical vector (cos_sim ≈ 1.0, drift ≈ 0.0)
_VEC_SIMILAR = [0.999] + [0.001] + [0.0] * 382
# Orthogonal vector (cos_sim = 0.0, drift = 1.0)
_VEC_ORTHOGONAL = [0.0, 1.0] + [0.0] * 382
# Opposite vector (cos_sim = -1.0, drift = 2.0)
_VEC_OPPOSITE = [-1.0] + [0.0] * 383


def _normalise(v: list[float]) -> list[float]:
    arr = np.array(v, dtype=np.float32)
    norm = np.linalg.norm(arr)
    return (arr / norm).tolist() if norm > 0 else arr.tolist()


_VEC_SIMILAR = _normalise(_VEC_SIMILAR)

_TRANSCRIPT_WITH_PAIN = [
    TranscriptLine(speaker="patient", text="I have sharp stabbing pain and burning", line_index=0),
    TranscriptLine(speaker="doctor", text="How long has this been going on?", line_index=1),
]

_TRANSCRIPT_WITH_NEG = [
    TranscriptLine(speaker="patient", text="I feel hopeless and exhausted, cannot sleep", line_index=0),
]

_TRANSCRIPT_DOCTOR_ONLY = [
    TranscriptLine(speaker="doctor", text="How are you feeling today?", line_index=0),
]

_TRANSCRIPT_NO_KEYWORDS = [
    TranscriptLine(speaker="patient", text="The weather is quite fine today.", line_index=0),
]


def _make_mock_db(return_vectors: list[list[float]]) -> AsyncMock:
    """Return an AsyncMock that acts as an AsyncSession accepting any query."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=AsyncMock(
        fetchall=lambda: [(v,) for v in return_vectors]
    ))
    return mock_db


# ---------------------------------------------------------------------------
# _extract_patient_speech
# ---------------------------------------------------------------------------


def test_extract_patient_speech_joins_patient_lines():
    lines = [
        TranscriptLine(speaker="patient", text="Hello", line_index=0),
        TranscriptLine(speaker="doctor", text="Hi there", line_index=1),
        TranscriptLine(speaker="patient", text="I hurt", line_index=2),
    ]
    result = _extract_patient_speech(lines)
    assert result == "Hello I hurt"


def test_extract_patient_speech_empty_when_no_patient_lines():
    lines = [TranscriptLine(speaker="doctor", text="Any concerns?", line_index=0)]
    assert _extract_patient_speech(lines) == ""


# ---------------------------------------------------------------------------
# _determine_direction
# ---------------------------------------------------------------------------


def test_direction_pain_keywords():
    assert _determine_direction("sharp stabbing pain and burning") == "increased_pain_descriptors"


def test_direction_negative_affect_keywords():
    assert _determine_direction("hopeless and exhausted cannot sleep") == "increased_negative_affect"


def test_direction_pain_wins_over_negative_when_both_present():
    # pain_count >= neg_count → pain wins
    assert _determine_direction("pain pain pain hopeless") == "increased_pain_descriptors"


def test_direction_fallback_when_no_keywords():
    # No matching keywords → conservative fallback
    assert _determine_direction("the weather is nice") == "increased_negative_affect"


# ---------------------------------------------------------------------------
# detect() — no patient speech
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_returns_none_when_no_patient_speech(monkeypatch):
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    result = await detect(_PATIENT_ID, _TRANSCRIPT_DOCTOR_ONLY, db=AsyncMock())
    assert result is None


# ---------------------------------------------------------------------------
# detect() — insufficient history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_returns_none_when_zero_prior_embeddings(monkeypatch):
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_PAIN, db=AsyncMock())
    assert result is None


@pytest.mark.asyncio
async def test_detect_returns_none_when_only_one_prior_embedding(monkeypatch):
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[_VEC_SIMILAR]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_PAIN, db=AsyncMock())
    assert result is None


# ---------------------------------------------------------------------------
# detect() — drift detected (high distance)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_flags_drift_when_orthogonal(monkeypatch):
    """cos_sim = 0.0 for orthogonal vectors → drift_score = 1.0 > threshold."""
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[_VEC_ORTHOGONAL, _VEC_ORTHOGONAL]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_PAIN, db=AsyncMock())
    assert result is not None
    assert result.flagged is True
    assert result.delta > result.threshold
    assert result.threshold == 0.25


@pytest.mark.asyncio
async def test_detect_direction_pain_when_flagged(monkeypatch):
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[_VEC_OPPOSITE, _VEC_OPPOSITE]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_PAIN, db=AsyncMock())
    assert result is not None
    assert result.flagged is True
    assert result.direction == "increased_pain_descriptors"


@pytest.mark.asyncio
async def test_detect_direction_negative_affect_when_flagged(monkeypatch):
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[_VEC_OPPOSITE, _VEC_OPPOSITE]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_NEG, db=AsyncMock())
    assert result is not None
    assert result.flagged is True
    assert result.direction == "increased_negative_affect"


# ---------------------------------------------------------------------------
# detect() — no drift (low distance)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_no_drift_when_very_similar(monkeypatch):
    """cos_sim ≈ 1.0 for nearly identical vectors → drift_score ≈ 0.0 < threshold."""
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[_VEC_A, _VEC_A, _VEC_A]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_PAIN, db=AsyncMock())
    assert result is not None
    assert result.flagged is False
    assert result.direction == "no_significant_drift"
    assert result.delta < result.threshold


# ---------------------------------------------------------------------------
# detect() — delta and threshold fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_delta_is_correct(monkeypatch):
    """With 2 orthogonal vectors: avg_cos_sim=0.0 → delta=1.0."""
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[_VEC_ORTHOGONAL, _VEC_ORTHOGONAL]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_PAIN, db=AsyncMock())
    assert result is not None
    assert abs(result.delta - 1.0) < 1e-4


@pytest.mark.asyncio
async def test_detect_threshold_matches_settings(monkeypatch):
    monkeypatch.setattr("services.drift_agent.embed_text", lambda t: _VEC_A)
    monkeypatch.setattr(
        "services.drift_agent._fetch_prior_speech_embeddings",
        AsyncMock(return_value=[_VEC_ORTHOGONAL, _VEC_ORTHOGONAL]),
    )
    result = await detect(_PATIENT_ID, _TRANSCRIPT_WITH_PAIN, db=AsyncMock())
    assert result is not None
    from core.config import settings
    assert result.threshold == settings.DRIFT_THRESHOLD
