"""Unit tests for the evaluation-harness metric math.

These are deterministic and DB-free. The two trust metrics exercise the real
grounding and de-id services so the harness can't silently drift from production.
"""
import pytest

from eval.metrics import hallucination_rate, phi_leak_rate, rouge_l, token_f1
from eval.report import aggregate, build_report
from eval.thresholds import Thresholds


# --- token_f1 / rouge_l --------------------------------------------------


def test_quality_identical_strings_score_one():
    text = "blood pressure improved since the dose change"
    assert token_f1(text, text) == pytest.approx(1.0)
    assert rouge_l(text, text) == pytest.approx(1.0)


def test_quality_disjoint_strings_score_zero():
    assert token_f1("alpha beta gamma", "delta epsilon zeta") == 0.0
    assert rouge_l("alpha beta gamma", "delta epsilon zeta") == 0.0


def test_quality_both_empty_is_one_one_empty_is_zero():
    assert token_f1("", "") == 1.0
    assert rouge_l("", "") == 1.0
    assert token_f1("something", "") == 0.0
    assert rouge_l("", "something") == 0.0


def test_token_f1_partial_overlap_is_between():
    score = token_f1("the cat sat", "the cat ran")
    assert 0.0 < score < 1.0


def test_rouge_l_rewards_order():
    # Same words, scrambled order: ROUGE-L (subsequence) penalises more than the
    # order-agnostic token-F1.
    pred = "a b c d"
    ref = "d c b a"
    assert rouge_l(pred, ref) < token_f1(pred, ref)


# --- phi_leak_rate -------------------------------------------------------


class _Patient:
    def __init__(self, full_name, dob):
        self.full_name = full_name
        self.dob = dob


def _line(idx, text, speaker="patient"):
    return {"line_index": idx, "speaker": speaker, "text": text}


def test_phi_leak_rate_zero_when_scrubbed():
    transcript = [
        _line(1, "Hi, I am Sarah Johnson and my number is 555-123-4567."),
    ]
    patient = _Patient("Sarah Johnson", "1985-07-14")
    rate = phi_leak_rate(transcript, patient, ["Sarah Johnson", "555-123-4567"])
    assert rate == 0.0


def test_phi_leak_rate_nonzero_when_identifier_survives():
    # The clinic name is PHI we did NOT teach the scrubber about, so it leaks —
    # this guards that the metric actually detects coverage gaps.
    transcript = [_line(1, "Seen at Lakeside Family Clinic today.")]
    patient = _Patient("Sarah Johnson", "1985-07-14")
    rate = phi_leak_rate(transcript, patient, ["Lakeside Family Clinic"])
    assert rate == 1.0


def test_phi_leak_rate_empty_planted_is_zero():
    assert phi_leak_rate([], _Patient("X", "2000-01-01"), []) == 0.0


# --- hallucination_rate --------------------------------------------------


@pytest.mark.asyncio
async def test_hallucination_rate_zero_for_grounded_note():
    transcript = [
        _line(1, "The headaches are much better since the higher lisinopril dose."),
    ]
    soap = {
        "subjective": {
            "text": "Headaches much better since the higher lisinopril dose.",
            "source_lines": [1],
        },
        "objective": {"text": "", "source_lines": []},
        "assessment": {"text": "", "source_lines": []},
        "plan": {"text": "", "source_lines": []},
    }
    assert await hallucination_rate(soap, transcript) == 0.0


@pytest.mark.asyncio
async def test_hallucination_rate_flags_fabricated_claim():
    transcript = [_line(1, "The patient reports a mild headache today.")]
    soap = {
        "subjective": {
            # One grounded sentence + one fabricated, uncited sentence.
            "text": "Patient reports a mild headache today. Patient also had a heart attack last year.",
            "source_lines": [1],
        },
        "objective": {"text": "", "source_lines": []},
        "assessment": {"text": "", "source_lines": []},
        "plan": {"text": "", "source_lines": []},
    }
    rate = await hallucination_rate(soap, transcript)
    assert rate == pytest.approx(0.5)


# --- aggregation + gate --------------------------------------------------


def test_gate_fails_on_phi_leak():
    cases = [
        {
            "id": "c1",
            "token_f1": 0.9,
            "rouge_l": 0.8,
            "hallucination_rate": 0.0,
            "phi_leak_rate": 0.5,  # any leak must fail the gate
            "residual_placeholders": 0,
        }
    ]
    report = build_report(cases, "replay", Thresholds(), gated=True)
    assert report["passed"] is False
    assert any("phi_leak_rate" in b for b in report["breaches"])


def test_gate_passes_clean_run_and_no_gate_never_fails():
    cases = [
        {
            "id": "c1",
            "token_f1": 0.9,
            "rouge_l": 0.8,
            "hallucination_rate": 0.0,
            "phi_leak_rate": 0.0,
            "residual_placeholders": 0,
        }
    ]
    assert build_report(cases, "replay", Thresholds(), gated=True)["passed"] is True

    bad = [dict(cases[0], phi_leak_rate=1.0)]
    report = build_report(bad, "replay", Thresholds(), gated=False)
    assert report["passed"] is True  # report-only never fails
    assert report["breaches"]  # ...but breaches are still recorded


def test_aggregate_means_across_cases():
    cases = [
        {"id": "a", "token_f1": 0.4, "rouge_l": 0.4, "hallucination_rate": 0.0, "phi_leak_rate": 0.0, "residual_placeholders": 0},
        {"id": "b", "token_f1": 0.6, "rouge_l": 0.6, "hallucination_rate": 0.2, "phi_leak_rate": 0.0, "residual_placeholders": 1},
    ]
    agg = aggregate(cases)
    assert agg["token_f1"] == pytest.approx(0.5)
    assert agg["hallucination_rate"] == pytest.approx(0.1)
    assert agg["residual_placeholders"] == 1
