"""Unit tests for services/history_retrieval.py — pure helpers and get_summaries.

sentence_transformers imports torch whose DLL fails to load on this machine
(missing Visual C++ runtime). We stub both packages in sys.modules before
importing any service module so the tests run without the native library.
"""
from __future__ import annotations

import sys
import types

import numpy as np

# ---------------------------------------------------------------------------
# Stub sentence_transformers BEFORE importing services.history_retrieval.
# history_retrieval imports services.embedding which imports sentence_transformers.
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

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.visit import Visit
from schemas.pipeline import SOAPField, SOAPNote
from services.history_retrieval import _soap_note_to_text, _summarise_past_visit, get_summaries


# ---------------------------------------------------------------------------
# _soap_note_to_text
# ---------------------------------------------------------------------------


def test_soap_note_to_text_concatenates_all_four_fields():
    soap = SOAPNote(
        subjective=SOAPField(text="chest pain"),
        objective=SOAPField(text="bp elevated"),
        assessment=SOAPField(text="hypertension"),
        plan=SOAPField(text="lisinopril"),
    )
    result = _soap_note_to_text(soap)
    for expected in ("chest pain", "bp elevated", "hypertension", "lisinopril"):
        assert expected in result


def test_soap_note_to_text_skips_empty_fields():
    soap = SOAPNote(
        subjective=SOAPField(text="cough"),
        objective=SOAPField(text=""),
        assessment=SOAPField(text="URI"),
        plan=SOAPField(text=""),
    )
    assert _soap_note_to_text(soap) == "cough URI"


def test_soap_note_to_text_all_empty_returns_empty_string():
    assert _soap_note_to_text(SOAPNote()) == ""


# ---------------------------------------------------------------------------
# _summarise_past_visit
# ---------------------------------------------------------------------------


def _make_visit(
    assessment: str = "Hypertension",
    plan: str = "Lisinopril 10mg",
    date: datetime | None = None,
) -> Visit:
    visit = MagicMock(spec=Visit)
    visit.visit_date = date or datetime(2026, 1, 15, tzinfo=timezone.utc)
    visit.soap_note = {
        "assessment": {"text": assessment},
        "plan": {"text": plan},
    }
    return visit


def test_summarise_past_visit_contains_date_and_similarity():
    result = _summarise_past_visit(_make_visit(), similarity=0.87)
    assert "2026-01-15" in result
    assert "0.87" in result


def test_summarise_past_visit_contains_assessment_and_plan():
    result = _summarise_past_visit(
        _make_visit(assessment="Type 2 diabetes", plan="Metformin 500mg"), similarity=0.5
    )
    assert "Type 2 diabetes" in result
    assert "Metformin 500mg" in result


def test_summarise_past_visit_truncates_long_text_to_200_chars():
    long_text = "x" * 300
    result = _summarise_past_visit(_make_visit(assessment=long_text), similarity=0.5)
    assessment_line = next(l for l in result.splitlines() if l.startswith("Assessment:"))
    assert len(assessment_line) <= len("Assessment: ") + 200


def test_summarise_past_visit_no_date_shows_unknown_date():
    visit = _make_visit()
    visit.visit_date = None
    result = _summarise_past_visit(visit, similarity=0.5)
    assert "unknown date" in result


def test_summarise_past_visit_missing_soap_fields_show_not_documented():
    visit = MagicMock(spec=Visit)
    visit.visit_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    visit.soap_note = {}
    result = _summarise_past_visit(visit, similarity=0.5)
    assert "not documented" in result


def test_summarise_past_visit_output_is_three_lines():
    result = _summarise_past_visit(_make_visit(), similarity=0.75)
    assert len(result.splitlines()) == 3


# ---------------------------------------------------------------------------
# get_summaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_summaries_returns_empty_for_empty_soap_note():
    db = AsyncMock()
    result = await get_summaries(SOAPNote(), uuid.uuid4(), db)
    assert result == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_summaries_returns_empty_when_no_prior_embeddings():
    sim_result = MagicMock()
    sim_result.all.return_value = []

    db = AsyncMock()
    db.execute.return_value = sim_result

    with patch("services.history_retrieval.embed_text", return_value=[0.1] * 384):
        result = await get_summaries(
            SOAPNote(subjective=SOAPField(text="headache")), uuid.uuid4(), db
        )

    assert result == []
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_summaries_returns_one_summary_per_matching_visit():
    vid = uuid.uuid4()

    sim_row = MagicMock()
    sim_row.visit_id = vid
    sim_row.similarity = 0.87

    sim_result = MagicMock()
    sim_result.all.return_value = [sim_row]

    fake_visit = MagicMock(spec=Visit)
    fake_visit.id = vid
    fake_visit.visit_date = datetime(2026, 1, 10, tzinfo=timezone.utc)
    fake_visit.soap_note = {
        "assessment": {"text": "Hypertension"},
        "plan": {"text": "Lisinopril 10mg"},
    }

    visit_result = MagicMock()
    visit_result.scalars.return_value.all.return_value = [fake_visit]

    db = AsyncMock()
    db.execute.side_effect = [sim_result, visit_result]

    with patch("services.history_retrieval.embed_text", return_value=[0.1] * 384):
        result = await get_summaries(
            SOAPNote(subjective=SOAPField(text="blood pressure high")), uuid.uuid4(), db
        )

    assert len(result) == 1
    assert "2026-01-10" in result[0]
    assert "0.87" in result[0]
    assert "Hypertension" in result[0]
    assert "Lisinopril" in result[0]


@pytest.mark.asyncio
async def test_get_summaries_preserves_similarity_order():
    vid1, vid2 = uuid.uuid4(), uuid.uuid4()

    sim_result = MagicMock()
    sim_result.all.return_value = [
        MagicMock(visit_id=vid1, similarity=0.95),
        MagicMock(visit_id=vid2, similarity=0.70),
    ]

    def _make(vid, assessment):
        v = MagicMock(spec=Visit)
        v.id = vid
        v.visit_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        v.soap_note = {"assessment": {"text": assessment}, "plan": {"text": "plan"}}
        return v

    visit_result = MagicMock()
    visit_result.scalars.return_value.all.return_value = [
        _make(vid1, "Diabetes"),
        _make(vid2, "Asthma"),
    ]

    db = AsyncMock()
    db.execute.side_effect = [sim_result, visit_result]

    with patch("services.history_retrieval.embed_text", return_value=[0.1] * 384):
        result = await get_summaries(
            SOAPNote(subjective=SOAPField(text="blood sugar")), uuid.uuid4(), db
        )

    assert len(result) == 2
    assert "0.95" in result[0] and "Diabetes" in result[0]
    assert "0.70" in result[1] and "Asthma" in result[1]
