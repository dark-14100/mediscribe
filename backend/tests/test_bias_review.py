"""Unit tests for services/bias_review.py.

All Groq HTTP calls are intercepted with respx so no real network traffic
occurs. Tests cover:
  - Happy path: flags returned and validated correctly.
  - Clean note: Groq returns empty array → empty list.
  - Unknown bias type: skipped without crashing.
  - Malformed items: skipped without crashing.
  - Unexpected JSON shape: returns empty list.
  - Invalid JSON from Groq: returns empty list.
  - No choices in Groq response: returns empty list.
  - Groq 4xx / 5xx: raises httpx.HTTPStatusError.
"""
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from schemas.pipeline import SOAPField, SOAPNote
from services.bias_review import GROQ_URL, review

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLEAN_SOAP = SOAPNote(
    subjective=SOAPField(text="Patient presents with lower back pain for two weeks."),
    objective=SOAPField(text="BP 130/80, HR 72, no acute distress."),
    assessment=SOAPField(text="Low back pain, likely musculoskeletal."),
    plan=SOAPField(text="Ibuprofen 400 mg TID, follow up in 2 weeks."),
)

_BIASED_SOAP = SOAPNote(
    subjective=SOAPField(text="Patient seems overly anxious as usual."),
    objective=SOAPField(text="Typical elderly complaint, probably nothing serious."),
    assessment=SOAPField(text="Patient is non-compliant as expected."),
    plan=SOAPField(text="Advised lifestyle changes."),
)


def _groq_response(bias_flags: list[dict]) -> Response:
    """Build a mock Groq chat-completion response."""
    body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"bias_flags": bias_flags})
                }
            }
        ]
    }
    return Response(200, json=body)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_returns_flags_for_biased_soap():
    """Flags are parsed and returned when Groq detects bias."""
    fake_flags = [
        {
            "phrase": "overly anxious as usual",
            "type": "gender_bias",
            "suggested_rewrite": "reports anxiety",
        },
        {
            "phrase": "typical elderly complaint",
            "type": "age_bias",
            "suggested_rewrite": "patient reports symptom",
        },
        {
            "phrase": "non-compliant as expected",
            "type": "socioeconomic_bias",
            "suggested_rewrite": "patient did not follow prior recommendations",
        },
    ]
    respx.post(GROQ_URL).mock(return_value=_groq_response(fake_flags))

    flags = await review(_BIASED_SOAP)

    assert len(flags) == 3
    assert flags[0].phrase == "overly anxious as usual"
    assert flags[0].type == "gender_bias"
    assert flags[0].suggested_rewrite == "reports anxiety"
    assert flags[1].type == "age_bias"
    assert flags[2].type == "socioeconomic_bias"


@pytest.mark.asyncio
@respx.mock
async def test_returns_empty_list_for_clean_note():
    """No flags are returned when Groq finds no bias."""
    respx.post(GROQ_URL).mock(return_value=_groq_response([]))

    flags = await review(_CLEAN_SOAP)

    assert flags == []


@pytest.mark.asyncio
@respx.mock
async def test_unknown_bias_type_is_skipped():
    """Items with an unrecognised bias type are silently dropped."""
    fake_flags = [
        {
            "phrase": "some phrase",
            "type": "cultural_bias",   # not a valid type
            "suggested_rewrite": "neutral phrase",
        },
        {
            "phrase": "overly anxious",
            "type": "gender_bias",
            "suggested_rewrite": "reports anxiety",
        },
    ]
    respx.post(GROQ_URL).mock(return_value=_groq_response(fake_flags))

    flags = await review(_CLEAN_SOAP)

    assert len(flags) == 1
    assert flags[0].type == "gender_bias"


@pytest.mark.asyncio
@respx.mock
async def test_malformed_items_are_skipped():
    """Items missing required keys are skipped without raising."""
    fake_flags = [
        {"type": "gender_bias"},            # missing phrase + suggested_rewrite
        {"phrase": "ok phrase", "type": "age_bias", "suggested_rewrite": "better"},
    ]
    respx.post(GROQ_URL).mock(return_value=_groq_response(fake_flags))

    flags = await review(_CLEAN_SOAP)

    assert len(flags) == 1
    assert flags[0].type == "age_bias"


@pytest.mark.asyncio
@respx.mock
async def test_bias_flags_not_a_list_returns_empty():
    """If 'bias_flags' is not an array the service returns [] without crashing."""
    body = {
        "choices": [
            {"message": {"content": json.dumps({"bias_flags": "sorry, none found"})}}
        ]
    }
    respx.post(GROQ_URL).mock(return_value=Response(200, json=body))

    flags = await review(_CLEAN_SOAP)

    assert flags == []


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_from_groq_returns_empty():
    """Unparseable JSON from Groq causes the service to return []."""
    body = {"choices": [{"message": {"content": "not json at all"}}]}
    respx.post(GROQ_URL).mock(return_value=Response(200, json=body))

    flags = await review(_CLEAN_SOAP)

    assert flags == []


@pytest.mark.asyncio
@respx.mock
async def test_no_choices_in_response_returns_empty():
    """If Groq returns no choices the service returns []."""
    body = {"choices": []}
    respx.post(GROQ_URL).mock(return_value=Response(200, json=body))

    flags = await review(_CLEAN_SOAP)

    assert flags == []


@pytest.mark.asyncio
@respx.mock
async def test_groq_500_raises():
    """A 5xx from Groq propagates as HTTPStatusError."""
    from httpx import HTTPStatusError

    respx.post(GROQ_URL).mock(return_value=Response(500, text="Internal Server Error"))

    with pytest.raises(HTTPStatusError):
        await review(_CLEAN_SOAP)


@pytest.mark.asyncio
@respx.mock
async def test_groq_401_raises():
    """A 401 from Groq (bad key) propagates as HTTPStatusError."""
    from httpx import HTTPStatusError

    respx.post(GROQ_URL).mock(return_value=Response(401, json={"error": "invalid key"}))

    with pytest.raises(HTTPStatusError):
        await review(_CLEAN_SOAP)


@pytest.mark.asyncio
@respx.mock
async def test_all_three_bias_types_accepted():
    """All three valid bias type literals are accepted by the parser."""
    fake_flags = [
        {"phrase": "p1", "type": "gender_bias", "suggested_rewrite": "r1"},
        {"phrase": "p2", "type": "age_bias", "suggested_rewrite": "r2"},
        {"phrase": "p3", "type": "socioeconomic_bias", "suggested_rewrite": "r3"},
    ]
    respx.post(GROQ_URL).mock(return_value=_groq_response(fake_flags))

    flags = await review(_CLEAN_SOAP)

    types = {f.type for f in flags}
    assert types == {"gender_bias", "age_bias", "socioeconomic_bias"}


@pytest.mark.asyncio
@respx.mock
async def test_flag_fields_preserved_exactly():
    """phrase and suggested_rewrite strings are preserved verbatim."""
    fake_flags = [
        {
            "phrase": "drug-seeking female",
            "type": "gender_bias",
            "suggested_rewrite": "patient requests pain management review",
        }
    ]
    respx.post(GROQ_URL).mock(return_value=_groq_response(fake_flags))

    flags = await review(_CLEAN_SOAP)

    assert flags[0].phrase == "drug-seeking female"
    assert flags[0].suggested_rewrite == "patient requests pain management review"


@pytest.mark.asyncio
@respx.mock
async def test_empty_content_from_groq_returns_empty():
    """Empty content string from Groq returns [] without crashing."""
    body = {"choices": [{"message": {"content": ""}}]}
    respx.post(GROQ_URL).mock(return_value=Response(200, json=body))

    flags = await review(_CLEAN_SOAP)

    assert flags == []


@pytest.mark.asyncio
@respx.mock
async def test_correct_groq_model_is_used():
    """Verifies the request is sent with the expected lighter model."""
    respx.post(GROQ_URL).mock(return_value=_groq_response([]))

    await review(_CLEAN_SOAP)

    call = respx.calls.last
    body = json.loads(call.request.content)
    assert body["model"] == "llama-3.1-8b-instant"


@pytest.mark.asyncio
@respx.mock
async def test_soap_fields_are_sent_to_groq():
    """All four SOAP field texts appear in the user message."""
    respx.post(GROQ_URL).mock(return_value=_groq_response([]))

    await review(_BIASED_SOAP)

    call = respx.calls.last
    body = json.loads(call.request.content)
    user_content = body["messages"][1]["content"]

    assert "overly anxious" in user_content
    assert "elderly complaint" in user_content
    assert "non-compliant" in user_content
