"""Unit tests for differential_agent — Groq calls are mocked."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.pipeline import SOAPField, SOAPNote
from services.differential_agent import diagnose


def _chest_pain_soap() -> SOAPNote:
    return SOAPNote(
        subjective=SOAPField(
            text="Chest pain on exertion for two weeks.",
            source_lines=[2],
        ),
        objective=SOAPField(
            text="BP 158/95. ECG normal sinus rhythm.",
            source_lines=[5],
        ),
        assessment=SOAPField(text="Suspected angina."),
        plan=SOAPField(text="Cardiology referral."),
    )


def _mock_groq_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.mark.asyncio
async def test_diagnose_parses_and_sorts_differentials():
    groq_payload = {
        "differentials": [
            {
                "diagnosis": "GERD",
                "confidence": 0.21,
                "contributing_fields": ["subjective"],
            },
            {
                "diagnosis": "Stable angina",
                "confidence": 0.74,
                "contributing_fields": ["subjective", "objective"],
            },
            {
                "diagnosis": "Hypertensive urgency",
                "confidence": 0.55,
                "contributing_fields": ["objective"],
            },
        ]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_groq_response(groq_payload))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.differential_agent.httpx.AsyncClient", return_value=mock_client):
        result = await diagnose(_chest_pain_soap())

    assert len(result) == 3
    assert result[0].diagnosis == "Stable angina"
    assert result[0].confidence == 0.74
    assert result[0].contributing_fields == ["subjective", "objective"]


@pytest.mark.asyncio
async def test_diagnose_filters_invalid_contributing_fields():
    groq_payload = {
        "differentials": [
            {
                "diagnosis": "Tension headache",
                "confidence": 0.6,
                "contributing_fields": ["subjective", "invalid_field"],
            }
        ]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_groq_response(groq_payload))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.differential_agent.httpx.AsyncClient", return_value=mock_client):
        result = await diagnose(_chest_pain_soap())

    assert len(result) == 1
    assert result[0].contributing_fields == ["subjective"]


@pytest.mark.asyncio
async def test_diagnose_empty_list():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_groq_response({"differentials": []}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.differential_agent.httpx.AsyncClient", return_value=mock_client):
        result = await diagnose(_chest_pain_soap())

    assert result == []
