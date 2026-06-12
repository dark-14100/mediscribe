"""Unit tests for anomaly_agent — Groq calls are mocked."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.pipeline import SOAPField, SOAPNote
from services.anomaly_agent import detect


def _sample_soap() -> SOAPNote:
    return SOAPNote(
        subjective=SOAPField(
            text="Denies chest pain today.",
            source_lines=[2],
        ),
        objective=SOAPField(
            text="BP 158/95, HR 82.",
            source_lines=[5],
        ),
        assessment=SOAPField(text="Hypertension, possible angina."),
        plan=SOAPField(text="Start aspirin 81 mg daily."),
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
async def test_detect_parses_anomalies():
    groq_payload = {
        "anomalies": [
            {
                "severity": "high",
                "type": "drug_interaction",
                "description": "Aspirin may interact with warfarin.",
                "source_line": 5,
            }
        ]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_groq_response(groq_payload))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.groq_retry.httpx.AsyncClient", return_value=mock_client):
        result = await detect(
            _sample_soap(),
            ["Date: 2025-01-01 | Similarity: 0.9\nAssessment: Stable angina\nPlan: Continue meds"],
            ["warfarin 5 mg daily"],
        )

    assert len(result) == 1
    assert result[0].severity == "high"
    assert result[0].type == "drug_interaction"
    assert result[0].source_line == 5
    assert "warfarin" in result[0].description.lower() or "aspirin" in result[0].description.lower()


@pytest.mark.asyncio
async def test_detect_empty_anomalies_array():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_groq_response({"anomalies": []}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.groq_retry.httpx.AsyncClient", return_value=mock_client):
        result = await detect(_sample_soap(), [], [])

    assert result == []


@pytest.mark.asyncio
async def test_detect_skips_invalid_items():
    groq_payload = {
        "anomalies": [
            {"severity": "high", "type": "drug_interaction", "description": "Valid flag.", "source_line": 1},
            {"severity": "critical", "type": "unknown", "description": "bad"},
        ]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_groq_response(groq_payload))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.groq_retry.httpx.AsyncClient", return_value=mock_client):
        result = await detect(_sample_soap(), [], ["metformin"])

    assert len(result) == 1
