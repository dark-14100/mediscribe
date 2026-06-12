"""Tests for the rules-only de-identification layer (services.deid).

These verify the deterministic scrub + reversible re-identification with no DB
and no LLM. The key invariants: originals never survive in the clean text, the
round-trip restores them, and the persisted report is PHI-free.
"""
import types
from datetime import date

from schemas.pipeline import TranscriptLine
from services.deid import (
    count_residual,
    deidentify_transcript,
    reidentify,
)


def _patient(full_name="Jane Doe", dob=date(1985, 7, 14)):
    return types.SimpleNamespace(full_name=full_name, dob=dob)


def _line(text, idx=1, speaker="patient"):
    return TranscriptLine(speaker=speaker, text=text, line_index=idx)


def _clean_text(result):
    return " ".join(t.text for t in result.transcript)


def test_known_name_and_dob_are_scrubbed():
    tr = [_line("Jane Doe was born 1985-07-14 and reports a headache.")]
    result = deidentify_transcript(tr, _patient())
    clean = _clean_text(result)
    assert "Jane" not in clean
    assert "Doe" not in clean
    assert "1985-07-14" not in clean
    assert "[PATIENT]" in clean
    assert "[DOB]" in clean


def test_regex_categories_are_detected():
    tr = [
        _line("Email jane@example.com phone 555-123-4567 ssn 123-45-6789 MRN: A1234")
    ]
    result = deidentify_transcript(tr, _patient(full_name="Nobody"))
    clean = _clean_text(result)
    assert "jane@example.com" not in clean
    assert "555-123-4567" not in clean
    assert "123-45-6789" not in clean
    report = result.report()
    assert report.applied is True
    assert report.by_category.get("email", 0) >= 1
    assert report.by_category.get("phone", 0) >= 1
    assert report.by_category.get("id", 0) >= 1


def test_round_trip_restores_original():
    original = "Jane Doe called from 555-123-4567 about jane@example.com"
    tr = [_line(original)]
    result = deidentify_transcript(tr, _patient())
    clean = _clean_text(result)
    restored = reidentify(clean, result.mapping)
    assert "Jane Doe" in restored
    assert "555-123-4567" in restored
    assert "jane@example.com" in restored


def test_same_value_maps_to_same_placeholder():
    tr = [
        _line("jane@example.com", idx=1),
        _line("contact jane@example.com again", idx=2),
    ]
    result = deidentify_transcript(tr, _patient(full_name="Nobody"))
    # Only one distinct email -> one placeholder in the map.
    email_placeholders = [k for k in result.mapping if k.startswith("[EMAIL")]
    assert len(email_placeholders) == 1


def test_reidentify_is_safe_on_mangled_placeholder():
    mapping = {"[DATE_1]": "March 3, 2026"}
    # LLM dropped/garbled the placeholder -> harmless leftover, never PHI.
    out = reidentify("seen on [DATE_2]", mapping)
    assert out == "seen on [DATE_2]"
    assert count_residual({"text": "[DATE_2]"}, mapping) == 0
    assert count_residual({"text": "[DATE_1]"}, mapping) == 1


def test_report_contains_no_phi():
    tr = [_line("Jane Doe, jane@example.com, 555-123-4567")]
    result = deidentify_transcript(tr, _patient())
    blob = result.report().model_dump_json()
    assert "Jane" not in blob
    assert "jane@example.com" not in blob
    assert "555-123-4567" not in blob


def test_reidentify_deep_walks_structures():
    tr = [_line("Jane Doe has a fever")]
    result = deidentify_transcript(tr, _patient())
    payload = {"soap": {"subjective": [_clean_text(result)]}}
    restored = reidentify(payload, result.mapping)
    assert "Jane Doe" in restored["soap"]["subjective"][0]
