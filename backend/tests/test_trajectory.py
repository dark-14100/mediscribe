"""Unit tests for the rule-based trajectory scoring engine."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from models.visit import Visit
from schemas.pipeline import DriftFlag
from services.trajectory import (
    _extract_top_keywords,
    _signal_anomaly_trend,
    _signal_drift_trend,
    _signal_symptom_recurrence,
    _signal_visit_frequency,
    _score_to_direction,
    compute,
)


# ---------------------------------------------------------------------------
# Visit factory helpers (don't hit the DB — pure in-memory ORM objects)
# ---------------------------------------------------------------------------


def _make_visit(
    *,
    visit_date: datetime,
    anomalies: list | None = None,
    drift_flag: dict | None = None,
    subjective_text: str = "",
    patient_id: uuid.UUID | None = None,
) -> Visit:
    pid = patient_id or uuid.uuid4()
    return Visit(
        id=uuid.uuid4(),
        patient_id=pid,
        doctor_id=uuid.uuid4(),
        visit_date=visit_date,
        anomalies=anomalies or [],
        differentials=[],
        drift_flag=drift_flag,
        compliance_notes=[],
        bias_flags=[],
        trajectory_watch_zones=[],
        soap_note={"subjective": {"text": subjective_text, "source_lines": []}},
        soap_audit_trail={},
    )


def _series(dates: list[datetime], **kwargs_per_visit) -> list[Visit]:
    """Build a chronologically ordered list of visits from parallel arrays."""
    n = len(dates)
    fields = {k: v for k, v in kwargs_per_visit.items() if isinstance(v, list)}
    visits = []
    for i, d in enumerate(dates):
        kwargs = {k: v[i] for k, v in fields.items()}
        visits.append(_make_visit(visit_date=d, **kwargs))
    return visits


# ---------------------------------------------------------------------------
# Score → direction mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,direction",
    [
        (5, "up"),
        (2, "up"),
        (1, "stable"),
        (0, "stable"),
        (-1, "stable"),
        (-2, "down"),
        (-10, "down"),
    ],
)
def test_score_to_direction(score, direction):
    assert _score_to_direction(score) == direction


# ---------------------------------------------------------------------------
# Signal 1 — Anomaly trend
# ---------------------------------------------------------------------------


def test_anomaly_trend_strictly_increasing_returns_minus2():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base, anomalies=[]),
        _make_visit(visit_date=base + timedelta(days=7), anomalies=[{"id": "1"}]),
        _make_visit(
            visit_date=base + timedelta(days=14),
            anomalies=[{"id": "1"}, {"id": "2"}],
        ),
    ]
    score, zone = _signal_anomaly_trend(visits)
    assert score == -2
    assert zone is not None and "increasing" in zone


def test_anomaly_trend_non_decreasing_returns_minus1():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base, anomalies=[{"id": "1"}]),
        _make_visit(visit_date=base + timedelta(days=7), anomalies=[{"id": "1"}]),
        _make_visit(
            visit_date=base + timedelta(days=14),
            anomalies=[{"id": "1"}, {"id": "2"}],
        ),
    ]
    score, zone = _signal_anomaly_trend(visits)
    assert score == -1
    assert zone is not None


def test_anomaly_trend_strictly_decreasing_returns_plus1():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base, anomalies=[{"id": "1"}, {"id": "2"}, {"id": "3"}]),
        _make_visit(visit_date=base + timedelta(days=7), anomalies=[{"id": "1"}, {"id": "2"}]),
        _make_visit(visit_date=base + timedelta(days=14), anomalies=[{"id": "1"}]),
    ]
    score, zone = _signal_anomaly_trend(visits)
    assert score == 1
    assert zone is None


def test_anomaly_trend_flat_returns_zero():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base + timedelta(days=i * 7), anomalies=[])
        for i in range(3)
    ]
    score, zone = _signal_anomaly_trend(visits)
    assert score == 0
    assert zone is None


def test_anomaly_trend_fewer_than_3_visits_returns_zero():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [_make_visit(visit_date=base, anomalies=[{"id": "x"}])]
    assert _signal_anomaly_trend(visits) == (0, None)


# ---------------------------------------------------------------------------
# Signal 2 — Drift trend
# ---------------------------------------------------------------------------


def _drift(flagged: bool) -> dict:
    return {"flagged": flagged, "direction": None, "delta": 0.1, "threshold": 0.25}


def test_drift_trend_no_flags_returns_plus1():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base + timedelta(days=i * 7), drift_flag=_drift(False))
        for i in range(3)
    ]
    assert _signal_drift_trend(visits, None) == (1, None)


def test_drift_trend_one_flag_returns_zero():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base, drift_flag=_drift(False)),
        _make_visit(visit_date=base + timedelta(days=7), drift_flag=_drift(True)),
        _make_visit(visit_date=base + timedelta(days=14), drift_flag=_drift(False)),
    ]
    assert _signal_drift_trend(visits, None) == (0, None)


def test_drift_trend_two_or_more_flags_returns_minus2():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base, drift_flag=_drift(True)),
        _make_visit(visit_date=base + timedelta(days=7), drift_flag=_drift(True)),
        _make_visit(visit_date=base + timedelta(days=14), drift_flag=_drift(False)),
    ]
    score, zone = _signal_drift_trend(visits, None)
    assert score == -2
    assert zone is not None and "Drift flagged" in zone


def test_drift_trend_current_drift_overlays_latest_visit_when_empty():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base, drift_flag=_drift(True)),
        _make_visit(visit_date=base + timedelta(days=7), drift_flag=None),
    ]
    current = DriftFlag(flagged=True, direction=None, delta=0.4, threshold=0.25)
    score, zone = _signal_drift_trend(visits, current)
    assert score == -2  # Two flagged visits now (first stored, second overlayed)
    assert zone is not None


# ---------------------------------------------------------------------------
# Signal 3 — Visit frequency
# ---------------------------------------------------------------------------


def test_visit_frequency_shortened_returns_minus1():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Gaps: 30d, 30d, 5d → avg 21.67d, latest 5d → 5 < 21.67*0.7 (15.17)
    dates = [base, base + timedelta(days=30), base + timedelta(days=60), base + timedelta(days=65)]
    visits = [_make_visit(visit_date=d) for d in dates]
    score, zone = _signal_visit_frequency(visits)
    assert score == -1
    assert zone is not None and "Visit frequency" in zone


def test_visit_frequency_stable_returns_zero():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dates = [base + timedelta(days=i * 10) for i in range(4)]
    visits = [_make_visit(visit_date=d) for d in dates]
    assert _signal_visit_frequency(visits) == (0, None)


def test_visit_frequency_fewer_than_4_visits_returns_zero():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [_make_visit(visit_date=base + timedelta(days=i * 7)) for i in range(3)]
    assert _signal_visit_frequency(visits) == (0, None)


# ---------------------------------------------------------------------------
# Signal 4 — Symptom recurrence
# ---------------------------------------------------------------------------


def test_extract_top_keywords_drops_stopwords_and_short_words():
    text = "Patient reports chest pain and shortness of breath. Chest pain again."
    out = _extract_top_keywords(text, n=5)
    # 'chest' and 'pain' should be in the top.
    assert "chest" in out
    assert "pain" in out
    # 'patient', 'reports', 'and', 'of' are stopwords or too short.
    assert "patient" not in out
    assert "reports" not in out


def test_symptom_recurrence_returns_negative_when_words_shared_across_3_visits():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(
            visit_date=base + timedelta(days=i * 7),
            subjective_text="Severe chest pain radiating down the left arm. Chest pain worsens at night.",
        )
        for i in range(3)
    ]
    score, zones = _signal_symptom_recurrence(visits)
    assert score <= -1
    assert any("chest" in z or "pain" in z for z in zones)


def test_symptom_recurrence_caps_at_minus_3():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Five shared keywords → would be -5, capped at -3.
    text = "Severe chest pain radiating down left arm with nausea sweating dizziness."
    visits = [
        _make_visit(visit_date=base + timedelta(days=i * 7), subjective_text=text)
        for i in range(3)
    ]
    score, _ = _signal_symptom_recurrence(visits)
    assert score == -3


def test_symptom_recurrence_no_overlap_returns_zero():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    visits = [
        _make_visit(visit_date=base, subjective_text="Routine annual physical examination."),
        _make_visit(
            visit_date=base + timedelta(days=30),
            subjective_text="Sprained ankle from running yesterday.",
        ),
        _make_visit(
            visit_date=base + timedelta(days=60),
            subjective_text="Sore throat with mild fever for two days.",
        ),
    ]
    assert _signal_symptom_recurrence(visits) == (0, [])


# ---------------------------------------------------------------------------
# End-to-end via compute() against a real test DB session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_returns_none_with_fewer_than_2_visits(
    db_session, doctor_user
):
    from models.patient import Patient

    patient = Patient(
        full_name="Sparse",
        dob=datetime(1980, 1, 1).date(),
        gender="m",
        doctor_id=doctor_user.id,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    result = await compute(patient.id, drift_flag=None, db=db_session)
    assert result is None


@pytest.mark.asyncio
async def test_compute_returns_declining_when_all_signals_negative(
    db_session, doctor_user
):
    """Seed 5 visits with worsening data → trajectory must be 'down'."""
    from models.patient import Patient

    patient = Patient(
        full_name="Declining",
        dob=datetime(1980, 1, 1).date(),
        gender="m",
        doctor_id=doctor_user.id,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    seeds = [
        (base, [], None, "general checkup"),
        (base + timedelta(days=30), [{"id": "1"}], _drift(True), "chest pain mild"),
        (
            base + timedelta(days=60),
            [{"id": "1"}, {"id": "2"}],
            _drift(True),
            "chest pain worsening",
        ),
        (
            base + timedelta(days=80),  # gap tightening: 20d after a 30d cadence
            [{"id": "1"}, {"id": "2"}, {"id": "3"}],
            _drift(False),
            "severe chest pain worsening",
        ),
        (
            base + timedelta(days=85),  # gap = 5d
            [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}],
            _drift(True),
            "severe chest pain unrelenting",
        ),
    ]
    for d, anoms, drift, subj in seeds:
        db_session.add(
            Visit(
                patient_id=patient.id,
                doctor_id=doctor_user.id,
                visit_date=d,
                anomalies=anoms,
                drift_flag=drift,
                soap_note={"subjective": {"text": subj, "source_lines": []}},
            )
        )
    await db_session.commit()

    result = await compute(patient.id, drift_flag=None, db=db_session)
    assert result is not None
    assert result.direction == "down"
    assert result.confidence == 100  # 5 visits
    assert result.computed_from_visits == 5
    assert len(result.watch_zones) >= 1


@pytest.mark.asyncio
async def test_compute_confidence_scales_with_visit_count(db_session, doctor_user):
    from models.patient import Patient

    patient = Patient(
        full_name="Two visits",
        dob=datetime(1980, 1, 1).date(),
        gender="f",
        doctor_id=doctor_user.id,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(2):
        db_session.add(
            Visit(
                patient_id=patient.id,
                doctor_id=doctor_user.id,
                visit_date=base + timedelta(days=i * 14),
                anomalies=[],
                drift_flag=_drift(False),
            )
        )
    await db_session.commit()

    result = await compute(patient.id, drift_flag=None, db=db_session)
    assert result is not None
    assert result.confidence == 40  # 2 / 5 * 100
    assert result.direction == "stable"
