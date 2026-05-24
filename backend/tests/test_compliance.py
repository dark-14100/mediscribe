"""Unit tests for services/compliance.py.

All Groq HTTP calls are intercepted with respx so no real network traffic
occurs. Tests cover:
  - Happy path: complete note → status="pass", empty notes list.
  - Empty plan field → status="fail", note references "plan".
  - Missing assessment → status="warn" or "fail" with an assessment note.
  - Multiple compliance issues → all notes returned.
  - Unknown status value from LLM → falls back to "warn".
  - Malformed note items → skipped without crashing.
  - Invalid JSON from Groq → returns ComplianceResult(status="warn", notes=[]).
  - No choices in Groq response → returns ComplianceResult(status="warn", notes=[]).
  - Groq 4xx/5xx → raises httpx.HTTPStatusError.
  - System prompt embeds HIPAA checklist and ICD-10 reference.
"""
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from schemas.pipeline import SOAPField, SOAPNote
from services.compliance import GROQ_CHAT_URL, check

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMPLETE_SOAP = SOAPNote(
    subjective=SOAPField(text="Patient reports sharp chest pain for 3 days, worse on exertion."),
    objective=SOAPField(text="BP 145/90, HR 88, SpO2 98%. Mild tenderness on palpation."),
    assessment=SOAPField(text="Chest pain, unspecified. Possible musculoskeletal origin."),
    plan=SOAPField(text="ECG ordered. Ibuprofen 400 mg TID. Follow up in 1 week."),
)

_EMPTY_PLAN_SOAP = SOAPNote(
    subjective=SOAPField(text="Patient has a cough for two weeks."),
    objective=SOAPField(text="HR 78, lungs clear to auscultation."),
    assessment=SOAPField(text="Acute upper respiratory infection."),
    plan=SOAPField(text=""),  # empty
)

_EMPTY_ASSESSMENT_SOAP = SOAPNote(
    subjective=SOAPField(text="Patient reports fatigue."),
    objective=SOAPField(text="BP 120/80, HR 70."),
    assessment=SOAPField(text=""),  # empty
    plan=SOAPField(text="Follow up in 2 weeks."),
)


def _groq_response(status: str, notes: list[dict]) -> Response:
    body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"status": status, "notes": notes})
                }
            }
        ]
    }
    return Response(200, json=body)


def _groq_raw_content(content: str) -> Response:
    body = {"choices": [{"message": {"content": content}}]}
    return Response(200, json=body)


# ---------------------------------------------------------------------------
# Happy path — complete note passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_complete_note_returns_pass():
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_response("pass", []))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "pass"
    assert result.notes == []


# ---------------------------------------------------------------------------
# Fail — empty required fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_empty_plan_returns_fail():
    notes = [
        {
            "field": "plan",
            "issue": "Plan field is empty; no treatment or follow-up documented.",
            "suggestion": "Add a specific treatment plan and follow-up timing.",
        }
    ]
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_response("fail", notes))
    result = await check(_EMPTY_PLAN_SOAP)
    assert result.status == "fail"
    assert len(result.notes) == 1
    assert result.notes[0].field == "plan"
    assert result.notes[0].issue != ""
    assert result.notes[0].suggestion != ""


@pytest.mark.asyncio
@respx.mock
async def test_empty_assessment_returns_fail_or_warn():
    notes = [
        {
            "field": "assessment",
            "issue": "Assessment is empty; no working diagnosis documented.",
            "suggestion": "Document a working diagnosis or clinical impression.",
        }
    ]
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_response("fail", notes))
    result = await check(_EMPTY_ASSESSMENT_SOAP)
    assert result.status in {"fail", "warn"}
    assert any(n.field == "assessment" for n in result.notes)


# ---------------------------------------------------------------------------
# Multiple compliance notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_multiple_compliance_notes_all_returned():
    notes = [
        {
            "field": "plan",
            "issue": "No follow-up timing specified.",
            "suggestion": "Add specific follow-up date.",
        },
        {
            "field": "assessment",
            "issue": "ICD-10 code not mappable from assessment text.",
            "suggestion": "Clarify diagnosis to enable ICD-10 coding.",
        },
    ]
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_response("warn", notes))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "warn"
    assert len(result.notes) == 2
    fields = {n.field for n in result.notes}
    assert "plan" in fields
    assert "assessment" in fields


# ---------------------------------------------------------------------------
# Malformed / edge-case LLM responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_unknown_status_defaults_to_warn():
    content = json.dumps({"status": "unknown_value", "notes": []})
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_raw_content(content))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "warn"


@pytest.mark.asyncio
@respx.mock
async def test_malformed_note_items_are_skipped():
    notes = [
        {"field": "plan"},  # missing issue and suggestion
        {"field": "assessment", "issue": "OK", "suggestion": "Do this"},
    ]
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_response("warn", notes))
    result = await check(_COMPLETE_SOAP)
    assert len(result.notes) == 1
    assert result.notes[0].field == "assessment"


@pytest.mark.asyncio
@respx.mock
async def test_notes_not_a_list_returns_empty_notes():
    content = json.dumps({"status": "pass", "notes": "not a list"})
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_raw_content(content))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "pass"
    assert result.notes == []


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_returns_warn_with_empty_notes():
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_raw_content("not valid json{{"))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "warn"
    assert result.notes == []


@pytest.mark.asyncio
@respx.mock
async def test_no_choices_returns_warn():
    body = {"choices": []}
    respx.post(GROQ_CHAT_URL).mock(return_value=Response(200, json=body))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "warn"
    assert result.notes == []


@pytest.mark.asyncio
@respx.mock
async def test_empty_content_returns_warn():
    body = {"choices": [{"message": {"content": ""}}]}
    respx.post(GROQ_CHAT_URL).mock(return_value=Response(200, json=body))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "warn"
    assert result.notes == []


@pytest.mark.asyncio
@respx.mock
async def test_non_dict_json_returns_warn():
    content = json.dumps(["not", "a", "dict"])
    respx.post(GROQ_CHAT_URL).mock(return_value=_groq_raw_content(content))
    result = await check(_COMPLETE_SOAP)
    assert result.status == "warn"


# ---------------------------------------------------------------------------
# Groq HTTP errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_groq_4xx_raises():
    respx.post(GROQ_CHAT_URL).mock(return_value=Response(401, json={"error": "unauthorized"}))
    with pytest.raises(Exception):
        await check(_COMPLETE_SOAP)


@pytest.mark.asyncio
@respx.mock
async def test_groq_5xx_raises():
    respx.post(GROQ_CHAT_URL).mock(return_value=Response(500, json={"error": "server error"}))
    with pytest.raises(Exception):
        await check(_COMPLETE_SOAP)


# ---------------------------------------------------------------------------
# System prompt content sanity check
# ---------------------------------------------------------------------------


def test_system_prompt_contains_hipaa_items():
    from services.compliance import SYSTEM_PROMPT
    from core.constants import HIPAA_DOCUMENTATION_CHECKLIST

    for item in HIPAA_DOCUMENTATION_CHECKLIST:
        assert item in SYSTEM_PROMPT, f"HIPAA item missing from prompt: {item}"


def test_system_prompt_contains_icd10_codes():
    from services.compliance import SYSTEM_PROMPT
    from core.constants import ICD10_PRIMARY_CARE

    for code in list(ICD10_PRIMARY_CARE.keys())[:5]:
        assert code in SYSTEM_PROMPT, f"ICD-10 code missing from prompt: {code}"
