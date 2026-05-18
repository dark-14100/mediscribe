"""Unit tests for services/embedding.py — pure helpers and async core logic.

sentence_transformers imports torch whose DLL fails to load on this machine
(missing Visual C++ runtime). We stub both packages in sys.modules before
importing any service module so the tests run without the native library.
"""
from __future__ import annotations

import sys
import types

import numpy as np

# ---------------------------------------------------------------------------
# Stub sentence_transformers BEFORE importing services.embedding.
# The real package tries to import torch which crashes on this machine.
# ---------------------------------------------------------------------------

class _FakeSentenceTransformer:
    def __init__(self, *args, **kwargs):
        pass

    def encode(self, text: str, normalize_embeddings: bool = False):
        rng = np.random.default_rng(abs(hash(text)) % (2 ** 32))
        vec = rng.random(384).astype("float32")
        if normalize_embeddings:
            vec = vec / np.linalg.norm(vec)
        return vec


_st_stub = types.ModuleType("sentence_transformers")
_st_stub.SentenceTransformer = _FakeSentenceTransformer
sys.modules.setdefault("sentence_transformers", _st_stub)

# ---------------------------------------------------------------------------
# Now safe to import the service under test
# ---------------------------------------------------------------------------

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.embedding import _embed_and_store, _extract_patient_speech, _soap_to_text, embed_text


# ---------------------------------------------------------------------------
# embed_text
# ---------------------------------------------------------------------------


def test_embed_text_returns_384_floats():
    vec = embed_text("patient reports headache")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)


def test_embed_text_is_normalized():
    vec = embed_text("some clinical text")
    magnitude = math.sqrt(sum(v * v for v in vec))
    assert abs(magnitude - 1.0) < 1e-5


def test_embed_text_different_inputs_produce_different_vectors():
    assert embed_text("headache and fever") != embed_text("fractured tibia")


# ---------------------------------------------------------------------------
# _soap_to_text
# ---------------------------------------------------------------------------


def test_soap_to_text_concatenates_all_four_fields():
    soap = {
        "subjective": {"text": "headache"},
        "objective": {"text": "no fever"},
        "assessment": {"text": "tension headache"},
        "plan": {"text": "ibuprofen"},
    }
    result = _soap_to_text(soap)
    for expected in ("headache", "no fever", "tension headache", "ibuprofen"):
        assert expected in result


def test_soap_to_text_skips_fields_with_empty_text():
    soap = {
        "subjective": {"text": "cough"},
        "objective": {"text": ""},
        "assessment": {"text": "viral URI"},
        "plan": {},
    }
    assert _soap_to_text(soap) == "cough viral URI"


def test_soap_to_text_handles_non_dict_field_value():
    soap = {
        "subjective": "raw string",
        "objective": {"text": "bp normal"},
        "assessment": {},
        "plan": {},
    }
    result = _soap_to_text(soap)
    assert "raw string" in result
    assert "bp normal" in result


def test_soap_to_text_empty_soap_returns_empty_string():
    assert _soap_to_text({}) == ""


# ---------------------------------------------------------------------------
# _extract_patient_speech
# ---------------------------------------------------------------------------


def test_extract_patient_speech_returns_only_patient_lines():
    transcript = (
        "[doctor] How long have you had this?\n"
        "[patient] About two weeks.\n"
        "[doctor] Any other symptoms?\n"
        "[patient] Just some fatigue."
    )
    result = _extract_patient_speech(transcript)
    assert result == "About two weeks. Just some fatigue."
    assert "[doctor]" not in result


def test_extract_patient_speech_strips_speaker_label():
    result = _extract_patient_speech("[patient] My chest hurts.")
    assert result == "My chest hurts."
    assert "[patient]" not in result


def test_extract_patient_speech_no_patient_lines_returns_empty():
    transcript = "[doctor] Examining now.\n[doctor] BP looks normal."
    assert _extract_patient_speech(transcript) == ""


def test_extract_patient_speech_empty_transcript_returns_empty():
    assert _extract_patient_speech("") == ""


# ---------------------------------------------------------------------------
# _embed_and_store — async core logic with mocked DB session
# ---------------------------------------------------------------------------


def _mock_session_ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_embed_and_store_skips_and_warns_when_visit_not_found(caplog):
    import logging

    mock_session = AsyncMock()
    mock_session.scalar.return_value = None

    with patch("services.embedding.AsyncSessionLocal", return_value=_mock_session_ctx(mock_session)):
        with caplog.at_level(logging.WARNING, logger="medscribe.embedding"):
            await _embed_and_store("00000000-0000-0000-0000-000000000001")

    assert "visit not found" in caplog.text
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_embed_and_store_calls_embed_text_twice_when_patient_speech_present():
    fake_visit = MagicMock()
    fake_visit.id = uuid.uuid4()
    fake_visit.patient_id = uuid.uuid4()
    fake_visit.soap_note = {"assessment": {"text": "hypertension"}, "plan": {"text": "lisinopril"}}
    fake_visit.raw_transcript = "[doctor] How are you?\n[patient] Feeling dizzy."

    mock_session = AsyncMock()
    mock_session.scalar.return_value = fake_visit

    with patch("services.embedding.AsyncSessionLocal", return_value=_mock_session_ctx(mock_session)):
        with patch("services.embedding.embed_text", return_value=[0.1] * 384) as mock_embed:
            await _embed_and_store(str(fake_visit.id))

    assert mock_embed.call_count == 2
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_embed_and_store_calls_embed_text_once_when_no_patient_speech():
    fake_visit = MagicMock()
    fake_visit.id = uuid.uuid4()
    fake_visit.patient_id = uuid.uuid4()
    fake_visit.soap_note = {"subjective": {"text": "back pain"}}
    fake_visit.raw_transcript = "[doctor] Examining the patient."

    mock_session = AsyncMock()
    mock_session.scalar.return_value = fake_visit

    with patch("services.embedding.AsyncSessionLocal", return_value=_mock_session_ctx(mock_session)):
        with patch("services.embedding.embed_text", return_value=[0.1] * 384) as mock_embed:
            await _embed_and_store(str(fake_visit.id))

    assert mock_embed.call_count == 1
