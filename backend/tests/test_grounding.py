"""Tests for the rules-only grounding gate (services.grounding.verify).

These verify *faithfulness* scoring only — no Groq, no DB. They lock in the
deterministic rules: citation presence, citation validity, and lexical overlap.
"""
import pytest

from schemas.pipeline import SOAPField, SOAPNote, TranscriptLine
from services.grounding import verify

_TRANSCRIPT = [
    TranscriptLine(speaker="doctor", text="What brings you in today?", line_index=1),
    TranscriptLine(
        speaker="patient",
        text="I have a severe headache and nausea since yesterday.",
        line_index=2,
    ),
    TranscriptLine(speaker="doctor", text="Any fever?", line_index=3),
    TranscriptLine(speaker="patient", text="No fever.", line_index=4),
]


def _field_by_name(result, name):
    return next(f for f in result.fields if f.field == name)


@pytest.mark.asyncio
async def test_well_cited_claim_is_grounded():
    soap = SOAPNote(
        subjective=SOAPField(
            text="Severe headache and nausea since yesterday.", source_lines=[2]
        ),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(text="", source_lines=[]),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    subj = _field_by_name(result, "subjective")
    assert subj.status == "grounded"
    assert subj.unsupported_claims == []
    # Note has only one non-empty (grounded) field -> overall grounded.
    assert result.status == "grounded"
    assert result.checked_with == "rules"


@pytest.mark.asyncio
async def test_missing_citation_is_ungrounded():
    soap = SOAPNote(
        subjective=SOAPField(text="Patient reports fever.", source_lines=[]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(text="", source_lines=[]),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    subj = _field_by_name(result, "subjective")
    assert subj.status == "ungrounded"
    assert subj.unsupported_claims
    assert "No cited" in subj.unsupported_claims[0].issue


@pytest.mark.asyncio
async def test_invalid_citation_is_flagged():
    soap = SOAPNote(
        subjective=SOAPField(text="", source_lines=[]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(text="Tension headache.", source_lines=[99]),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    assess = _field_by_name(result, "assessment")
    assert assess.status == "ungrounded"
    assert assess.cited_lines_valid is False


@pytest.mark.asyncio
async def test_hallucinated_claim_is_ungrounded():
    # Plan invents a drug never mentioned, but cites a real (unrelated) line.
    soap = SOAPNote(
        subjective=SOAPField(text="", source_lines=[]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(text="", source_lines=[]),
        plan=SOAPField(text="Start amoxicillin 500mg twice daily.", source_lines=[2]),
    )
    result = await verify(soap, _TRANSCRIPT)
    plan = _field_by_name(result, "plan")
    assert plan.status == "ungrounded"
    assert result.status == "ungrounded"


@pytest.mark.asyncio
async def test_empty_note_is_trivially_grounded():
    soap = SOAPNote(
        subjective=SOAPField(text="", source_lines=[]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(text="", source_lines=[]),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    assert result.status == "grounded"
    assert result.confidence == 1.0
    assert all(not f.unsupported_claims for f in result.fields)


@pytest.mark.asyncio
async def test_overall_status_reflects_worst_field():
    soap = SOAPNote(
        subjective=SOAPField(
            text="Severe headache and nausea since yesterday.", source_lines=[2]
        ),
        objective=SOAPField(text="No fever.", source_lines=[4]),
        assessment=SOAPField(text="Tension headache.", source_lines=[99]),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    # subjective + objective grounded, assessment invalid-citation -> overall worst.
    assert _field_by_name(result, "subjective").status == "grounded"
    assert result.status == "ungrounded"
