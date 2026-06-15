"""Tests for the rules-only grounding gate (services.grounding.verify).

These verify *faithfulness* scoring only — no Groq, no DB. They lock in the
deterministic rules: citation presence, citation validity, and lexical overlap.
"""
import pytest

from schemas.pipeline import ClinicalNote, SOAPField, SOAPNote, TranscriptLine
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
async def test_soap_clinical_note_matches_soapnote():
    """Grounding a ClinicalNote(soap) is identical to grounding a SOAPNote."""
    soap = SOAPNote(
        subjective=SOAPField(
            text="Severe headache and nausea since yesterday.", source_lines=[2]
        ),
        assessment=SOAPField(text="Headache.", source_lines=[2]),
    )
    r_soap = await verify(soap, _TRANSCRIPT)
    r_clinical = await verify(ClinicalNote.from_soap(soap), _TRANSCRIPT)
    assert r_soap.model_dump() == r_clinical.model_dump()


@pytest.mark.asyncio
async def test_hp_note_grades_its_own_sections():
    """A non-SOAP note is graded against its template's sections, not S/O/A/P."""
    note = ClinicalNote.from_sections(
        "hp",
        {
            "chief_complaint": {"text": "Severe headache.", "source_lines": [2]},
            "hpi": {"text": "Since yesterday, with nausea.", "source_lines": [2]},
            "assessment": {"text": "Tension headache.", "source_lines": [2]},
            "plan": {"text": "", "source_lines": []},
        },
    )
    result = await verify(note, _TRANSCRIPT)
    fields = {f.field for f in result.fields}
    assert "chief_complaint" in fields and "hpi" in fields
    assert "subjective" not in fields


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


# --- Phase B: optional LLM verifier (Layer 2) ------------------------------


def _install_fake_groq(monkeypatch, *, verdict=None, raises=False, calls=None):
    """Patch services.groq_retry.chat_completion (resolved lazily by grounding)
    to echo a fixed verdict for every claim, recording which fields were sent."""
    import services.groq_retry as groq

    async def fake_chat_completion(*, model, messages, label, max_tokens, **kwargs):
        import json

        payload = json.loads(messages[1]["content"])
        if calls is not None:
            calls.append(payload["field"])
        if raises:
            raise RuntimeError("groq down")
        verdicts = [
            {"id": c["id"], "verdict": verdict, "reason": "meaning differs"}
            for c in payload["claims"]
        ]
        return {"choices": [{"message": {"content": json.dumps({"verdicts": verdicts})}}]}

    monkeypatch.setattr(groq, "chat_completion", fake_chat_completion)


def _enable_llm(monkeypatch, fields="assessment,plan"):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_USE_LLM", True)
    monkeypatch.setattr(settings, "GROUNDING_LLM_FIELDS", fields)


@pytest.mark.asyncio
async def test_llm_downgrades_grounded_claim(monkeypatch):
    _enable_llm(monkeypatch)
    _install_fake_groq(monkeypatch, verdict="NOT_SUPPORTED")
    soap = SOAPNote(
        subjective=SOAPField(text="", source_lines=[]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(
            text="Severe headache and nausea since yesterday.", source_lines=[2]
        ),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    assess = _field_by_name(result, "assessment")
    assert assess.status == "ungrounded"  # rules grounded, LLM tightened it
    assert result.checked_with == "rules+llm"
    assert assess.unsupported_claims[0].issue == "meaning differs"


@pytest.mark.asyncio
async def test_llm_cannot_upgrade_partial_claim(monkeypatch):
    _enable_llm(monkeypatch)
    _install_fake_groq(monkeypatch, verdict="SUPPORTED")
    # "Severe headache and chronic fatigue today." vs line 2 -> ~0.4 overlap = partial.
    soap = SOAPNote(
        subjective=SOAPField(text="", source_lines=[]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(
            text="Severe headache and chronic fatigue today.", source_lines=[2]
        ),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    assess = _field_by_name(result, "assessment")
    assert assess.status == "partial"  # downgrade-only: LLM "SUPPORTED" can't raise it


@pytest.mark.asyncio
async def test_llm_failure_keeps_rules_result(monkeypatch):
    _enable_llm(monkeypatch)
    _install_fake_groq(monkeypatch, raises=True)
    soap = SOAPNote(
        subjective=SOAPField(text="", source_lines=[]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(
            text="Severe headache and nausea since yesterday.", source_lines=[2]
        ),
        plan=SOAPField(text="", source_lines=[]),
    )
    result = await verify(soap, _TRANSCRIPT)
    assess = _field_by_name(result, "assessment")
    assert assess.status == "grounded"  # preserved
    assert result.checked_with == "rules"  # no degrade flag flipped


@pytest.mark.asyncio
async def test_llm_only_called_for_configured_fields(monkeypatch):
    calls: list[str] = []
    _enable_llm(monkeypatch, fields="assessment")  # plan excluded
    _install_fake_groq(monkeypatch, verdict="SUPPORTED", calls=calls)
    soap = SOAPNote(
        subjective=SOAPField(
            text="Severe headache and nausea since yesterday.", source_lines=[2]
        ),
        objective=SOAPField(text="No fever.", source_lines=[4]),
        assessment=SOAPField(text="Severe headache reported.", source_lines=[2]),
        plan=SOAPField(text="No fever today.", source_lines=[4]),
    )
    await verify(soap, _TRANSCRIPT)
    assert calls == ["assessment"]  # never subjective/objective/plan


# --- Phase B: cross-lingual grounding (note language != transcript language) ---


def _xlingual_soap():
    # English note cited against an English transcript, but we *declare* it
    # cross-lingual so the lexical layer is bypassed in favour of the LLM.
    return SOAPNote(
        subjective=SOAPField(text="Patient reports severe headache.", source_lines=[2]),
        objective=SOAPField(text="", source_lines=[]),
        assessment=SOAPField(text="Tension headache.", source_lines=[2]),
        plan=SOAPField(text="Recommend ibuprofen.", source_lines=[2]),
    )


@pytest.mark.asyncio
async def test_cross_lingual_uses_llm_authoritatively(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_CROSS_LINGUAL", True)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")
    # LLM (cross-lingual judge) says every cited claim is supported.
    _install_fake_groq(monkeypatch, verdict="SUPPORTED")
    result = await verify(
        _xlingual_soap(), _TRANSCRIPT, note_language="en", transcript_language="es"
    )
    assert result.cross_lingual is True
    assert result.checked_with == "llm-crosslingual"
    # Authoritative SUPPORTED verdict grounds the cited claims (lexical ignored).
    assert result.status == "grounded"


@pytest.mark.asyncio
async def test_cross_lingual_llm_can_flag_unsupported(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_CROSS_LINGUAL", True)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")
    _install_fake_groq(monkeypatch, verdict="NOT_SUPPORTED")
    result = await verify(
        _xlingual_soap(), _TRANSCRIPT, note_language="en", transcript_language="es"
    )
    assert result.cross_lingual is True
    assert result.status == "ungrounded"


@pytest.mark.asyncio
async def test_cross_lingual_degrades_to_review_without_llm(monkeypatch):
    from core.config import settings

    # No Groq key -> cannot verify cross-lingually -> flag for manual review,
    # never silently pass on bogus lexical scores.
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    result = await verify(
        _xlingual_soap(), _TRANSCRIPT, note_language="en", transcript_language="es"
    )
    assert result.cross_lingual is True
    assert result.checked_with == "crosslingual-unverified"
    assert result.status == "partial"


@pytest.mark.asyncio
async def test_same_language_is_not_cross_lingual():
    # Identical note/transcript language -> the rules path, unchanged.
    result = await verify(
        _xlingual_soap(), _TRANSCRIPT, note_language="en", transcript_language="en"
    )
    assert result.cross_lingual is False
    assert result.checked_with == "rules"
