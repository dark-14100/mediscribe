"""Smoke test for seed/seed_demo_data.py — verifies the PRD §12 demo contract.

The seed script is hand-authored content meant to drive a live demo. These
tests pin the contract so that a future edit to the script can't silently
break the demo:

    * 6 visits exist
    * Visit 3 is the first to carry a drift flag (PRD §12)
    * Visit 4 has at least one anomaly + a declining persisted trajectory
    * Visit 5 has 3 injected compliance violations (PRD §12)
    * Visit 6 has 2 bias flags + the final 'down' trajectory
    * Running the live ``services.trajectory.compute`` against the seeded
      patient independently returns ``direction='down'``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make seed/ importable when running pytest from backend/.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from seed.seed_demo_data import _build_visits  # noqa: E402
from services.trajectory import compute as compute_trajectory  # noqa: E402


# ---------------------------------------------------------------------------
# Pure-function shape / contract tests on _build_visits
# ---------------------------------------------------------------------------


def _visits():
    import uuid

    return _build_visits(patient_id=uuid.uuid4(), doctor_id=uuid.uuid4())


def test_seed_produces_exactly_six_visits():
    assert len(_visits()) == 6


def test_visits_are_chronologically_ordered():
    visits = _visits()
    for prev, nxt in zip(visits, visits[1:]):
        assert prev.visit_date < nxt.visit_date


def test_visit_1_and_2_have_no_drift_or_anomalies():
    visits = _visits()
    for v in visits[:2]:
        assert v.drift_flag is not None and v.drift_flag["flagged"] is False
        assert v.anomalies == []
        assert v.compliance_notes == []
        assert v.bias_flags == []


def test_visit_3_is_first_drift_flag():
    visits = _visits()
    # Visit 1 and 2: not flagged
    assert visits[0].drift_flag["flagged"] is False
    assert visits[1].drift_flag["flagged"] is False
    # Visit 3: flagged for the first time
    assert visits[2].drift_flag is not None
    assert visits[2].drift_flag["flagged"] is True
    assert visits[2].anomalies == []  # drift only, no anomaly yet


def test_visit_4_first_anomaly_and_declining_trajectory_recorded():
    v4 = _visits()[3]
    assert len(v4.anomalies) >= 1
    assert v4.trajectory_direction == "down"
    assert v4.trajectory_score is not None and v4.trajectory_score < 0


def test_visit_5_has_three_injected_compliance_violations():
    v5 = _visits()[4]
    assert len(v5.compliance_notes) == 3
    assert v5.compliance_status == "fail"
    # Each note must carry the schema fields the frontend renders against.
    for note in v5.compliance_notes:
        assert {"field", "issue", "suggestion"} <= note.keys()


def test_visit_6_has_two_bias_flags_and_down_trajectory():
    v6 = _visits()[5]
    assert len(v6.bias_flags) == 2
    assert v6.trajectory_direction == "down"
    assert v6.trajectory_score is not None and v6.trajectory_score <= -2
    assert len(v6.trajectory_watch_zones) >= 3
    # Visit 6 is intentionally unsigned so the demo opens on a workable note.
    assert v6.is_signed is False
    # Both bias-flag types from the PRD success metrics must appear.
    bias_types = {b["type"] for b in v6.bias_flags}
    assert bias_types == {"socioeconomic_bias", "age_bias"}
    # Each bias flag must carry the canonical schema fields.
    for flag in v6.bias_flags:
        assert {"phrase", "type", "suggested_rewrite"} <= flag.keys()


def test_soap_notes_use_four_required_fields():
    for v in _visits():
        assert set(v.soap_note.keys()) == {
            "subjective",
            "objective",
            "assessment",
            "plan",
        }
        for field in v.soap_note.values():
            assert "text" in field and "source_lines" in field


def test_all_anomalies_carry_required_schema_fields():
    for v in _visits():
        for a in v.anomalies:
            assert {"id", "severity", "type", "description", "source_line"} <= a.keys()
            assert a["severity"] in {"high", "medium", "low"}
            assert a["type"] in {
                "drug_interaction",
                "contradictory_symptom",
                "outlier_vital",
            }


# ---------------------------------------------------------------------------
# Integration test: feed the built visits into the test DB and verify the
# live trajectory engine independently agrees with the seeded direction.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_trajectory_engine_returns_down_for_seeded_patient(
    db_session, doctor_user
):
    from datetime import date as _date

    from models.patient import Patient

    patient = Patient(
        full_name="Maria Demo",
        dob=_date(1967, 4, 15),
        gender="female",
        doctor_id=doctor_user.id,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # Build visits using the seed's _build_visits, but re-point them at the
    # actual test patient/doctor IDs.
    visits = _build_visits(patient_id=patient.id, doctor_id=doctor_user.id)
    for v in visits:
        db_session.add(v)
    await db_session.commit()

    result = await compute_trajectory(patient.id, drift_flag=None, db=db_session)
    assert result is not None
    assert result.direction == "down"
    assert result.confidence == 100  # 5+ visits
    assert result.computed_from_visits == 5
    assert len(result.watch_zones) >= 1
