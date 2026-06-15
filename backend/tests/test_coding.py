"""Unit tests for the coding agent — Groq calls are mocked."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings
from schemas.pipeline import SOAPField, SOAPNote
from services.coding import generate_codes


def _soap() -> SOAPNote:
    return SOAPNote(
        subjective=SOAPField(text="Sore throat and cough for three days.", source_lines=[2]),
        objective=SOAPField(text="Temp 38.1C. Pharynx erythematous. ECG performed.", source_lines=[5, 6]),
        assessment=SOAPField(text="Acute upper respiratory infection.", source_lines=[8]),
        plan=SOAPField(text="Supportive care. Venipuncture for CBC.", source_lines=[10]),
    )


def _mock_groq_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }
    response.raise_for_status = MagicMock()
    return response


def _patched_client(payload: dict):
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_groq_response(payload))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return patch("services.groq_retry.httpx.AsyncClient", return_value=mock_client)


@pytest.mark.asyncio
async def test_generate_codes_parses_all_systems():
    payload = {
        "icd10": [
            {"code": "J06.9", "description": "URI", "confidence": 0.9, "evidence_field": "assessment", "rationale": "Documented URI."},
        ],
        "cpt": [
            {"code": "93000", "description": "ECG", "confidence": 0.7, "evidence_field": "objective", "rationale": "ECG performed."},
            {"code": "36415", "description": "Blood draw", "confidence": 0.6, "evidence_field": "plan", "rationale": "Venipuncture."},
        ],
        "em": {"code": "99214", "confidence": 0.65, "evidence_field": "plan", "rationale": "Moderate complexity."},
    }
    with _patched_client(payload):
        result = await generate_codes(_soap(), patient_class="established")

    assert [c.code for c in result.icd10] == ["J06.9"]
    assert {c.code for c in result.cpt} == {"93000", "36415"}
    assert result.em is not None and result.em.code == "99214"
    # Canonical description is filled from the reference table for known codes.
    assert result.icd10[0].description == "Acute upper respiratory infection, unspecified"
    # Evidence lines are pulled from the SOAP field's source_lines.
    assert result.icd10[0].evidence_lines == [8]


@pytest.mark.asyncio
async def test_generate_codes_for_hp_note_uses_template_sections():
    """A non-SOAP ClinicalNote is coded against its own sections; evidence_field
    + source_lines resolve from the template sections, not S/O/A/P."""
    from schemas.pipeline import ClinicalNote

    note = ClinicalNote.from_sections(
        "hp",
        {
            "chief_complaint": {"text": "Sore throat", "source_lines": [1]},
            "exam": {"text": "Pharynx red. ECG performed.", "source_lines": [5]},
            "assessment": {"text": "URI", "source_lines": [8]},
            "plan": {"text": "Supportive care", "source_lines": [10]},
        },
    )
    payload = {
        "icd10": [{"code": "J06.9", "confidence": 0.9, "evidence_field": "assessment"}],
        "cpt": [{"code": "93000", "confidence": 0.7, "evidence_field": "exam"}],
        "em": None,
    }
    with _patched_client(payload):
        result = await generate_codes(note, patient_class="established")

    assert [c.code for c in result.icd10] == ["J06.9"]
    assert result.icd10[0].evidence_lines == [8]
    # CPT evidence comes from the H&P "exam" section, not a SOAP field.
    assert result.cpt[0].evidence_field == "exam"
    assert result.cpt[0].evidence_lines == [5]


@pytest.mark.asyncio
async def test_invalid_codes_are_dropped():
    payload = {
        "icd10": [
            {"code": "NOTACODE", "confidence": 0.9, "evidence_field": "assessment"},
            {"code": "J06.9", "confidence": 0.8, "evidence_field": "assessment"},
        ],
        "cpt": [{"code": "abc", "confidence": 0.5}],
        "em": None,
    }
    with _patched_client(payload):
        result = await generate_codes(_soap())

    assert [c.code for c in result.icd10] == ["J06.9"]
    assert result.cpt == []
    assert result.em is None


@pytest.mark.asyncio
async def test_em_validated_against_patient_class():
    # 99214 is an established-patient code — invalid for a NEW patient.
    payload = {"icd10": [], "cpt": [], "em": {"code": "99214", "confidence": 0.7}}
    with _patched_client(payload):
        result = await generate_codes(_soap(), patient_class="new")
    assert result.em is None
    assert result.patient_class == "new"

    # A valid new-patient code is kept.
    payload = {"icd10": [], "cpt": [], "em": {"code": "99204", "confidence": 0.7}}
    with _patched_client(payload):
        result = await generate_codes(_soap(), patient_class="new")
    assert result.em is not None and result.em.code == "99204"


@pytest.mark.asyncio
async def test_max_codes_cap(monkeypatch):
    monkeypatch.setattr(settings, "CODING_MAX_CODES", 2)
    payload = {
        "icd10": [
            {"code": "J06.9", "confidence": 0.9, "evidence_field": "assessment"},
            {"code": "R51", "confidence": 0.4, "evidence_field": "assessment"},
        ],
        "cpt": [
            {"code": "93000", "confidence": 0.8, "evidence_field": "objective"},
            {"code": "36415", "confidence": 0.3, "evidence_field": "plan"},
        ],
        "em": None,
    }
    with _patched_client(payload):
        result = await generate_codes(_soap())

    total = len(result.icd10) + len(result.cpt)
    assert total == 2
    # Highest-confidence survive: J06.9 (0.9) and 93000 (0.8).
    assert [c.code for c in result.icd10] == ["J06.9"]
    assert [c.code for c in result.cpt] == ["93000"]


@pytest.mark.asyncio
async def test_include_em_disabled(monkeypatch):
    monkeypatch.setattr(settings, "CODING_INCLUDE_EM", False)
    payload = {"icd10": [], "cpt": [], "em": {"code": "99213", "confidence": 0.7}}
    with _patched_client(payload):
        result = await generate_codes(_soap())
    assert result.em is None


@pytest.mark.asyncio
async def test_malformed_json_returns_empty_result():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"choices": [{"message": {"content": "not json {"}}]}
    response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.groq_retry.httpx.AsyncClient", return_value=mock_client):
        result = await generate_codes(_soap())

    assert result.icd10 == [] and result.cpt == [] and result.em is None


@pytest.mark.asyncio
async def test_duplicate_codes_deduped():
    payload = {
        "icd10": [
            {"code": "J06.9", "confidence": 0.9, "evidence_field": "assessment"},
            {"code": "J06.9", "confidence": 0.5, "evidence_field": "assessment"},
        ],
        "cpt": [],
        "em": None,
    }
    with _patched_client(payload):
        result = await generate_codes(_soap())
    assert [c.code for c in result.icd10] == ["J06.9"]
