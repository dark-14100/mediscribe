"""Seed the demo doctor, demo patient, and 6 progressively worsening visits.

Usage (from the repo root):

    python seed/seed_demo_data.py

The script is idempotent: it deletes any prior demo doctor (and cascades to
patients/visits via the FK constraints) before recreating everything. Safe to
run repeatedly.

The seeded data targets PRD §12 success metrics:
  - Visit 3 has the first drift flag
  - Visit 4 has the first anomaly + declining trajectory starts
  - Visit 5 has 3 injected HIPAA compliance violations
  - Visit 6 has 2 bias flags + a confirmed downward trajectory with watch zones
  - The demo doctor has 6 sessions today (cognitive-load nudge ready)

The hand-authored content lets the frontend demo the "wow moment" even before
the AI services are wired in. After insert, this script also runs the real
``services.trajectory.compute`` against the seeded patient to verify the
direction comes out as ``"down"`` — i.e. the rule-based engine independently
agrees with the hand-authored ``trajectory_direction`` on visit 6.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make backend/ importable when running this from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from sqlalchemy import delete, select  # noqa: E402

from core.security import hash_password  # noqa: E402
from db.session import AsyncSessionLocal, engine  # noqa: E402
from models.patient import Patient  # noqa: E402
from models.user import User  # noqa: E402
from models.visit import Visit  # noqa: E402
from services.trajectory import compute as compute_trajectory  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="[seed] %(message)s", stream=sys.stdout
)
log = logging.getLogger("seed")


# ---------------------------------------------------------------------------
# Demo identities
# ---------------------------------------------------------------------------

DEMO_EMAIL = "dr.demo@medscribe.test"
DEMO_PASSWORD = "demo1234"  # noqa: S105 — well-known demo credential
DEMO_DOCTOR_NAME = "Dr. Sasha Demo"

DEMO_PATIENT_NAME = "Maria Hernandez"
DEMO_PATIENT_DOB = date(1967, 4, 15)
DEMO_PATIENT_GENDER = "female"
DEMO_PATIENT_ALLERGIES = ["penicillin"]
DEMO_PATIENT_MEDS = [
    "metformin 500 mg twice daily",
    "lisinopril 10 mg daily",
    "atorvastatin 20 mg nightly",
]


# ---------------------------------------------------------------------------
# Helpers to build SOAP / drift / anomaly / compliance / bias payloads
# ---------------------------------------------------------------------------


def _soap(
    subjective: str,
    objective: str,
    assessment: str,
    plan: str,
    source_lines: int = 12,
) -> dict:
    """Build a SOAP note shaped exactly per SYSTEM_PROMPT §Key JSON Schemas."""
    return {
        "subjective": {"text": subjective, "source_lines": [1, 2, 3]},
        "objective": {"text": objective, "source_lines": [4, 5, 6]},
        "assessment": {"text": assessment, "source_lines": [7, 8, 9]},
        "plan": {"text": plan, "source_lines": [10, 11, source_lines]},
    }


def _drift(
    flagged: bool,
    direction: str | None,
    delta: float,
    threshold: float = 0.25,
) -> dict:
    return {
        "flagged": flagged,
        "direction": direction,
        "delta": round(delta, 3),
        "threshold": threshold,
    }


def _anomaly(severity: str, type_: str, description: str, source_line: int) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "severity": severity,
        "type": type_,
        "description": description,
        "source_line": source_line,
    }


def _compliance(field: str, issue: str, suggestion: str) -> dict:
    return {"field": field, "issue": issue, "suggestion": suggestion}


def _bias(phrase: str, type_: str, rewrite: str) -> dict:
    return {"phrase": phrase, "type": type_, "suggested_rewrite": rewrite}


# ---------------------------------------------------------------------------
# Visit script — hand-authored to demo a clear declining trajectory
# ---------------------------------------------------------------------------


def _build_visits(patient_id: uuid.UUID, doctor_id: uuid.UUID) -> list[Visit]:
    """Six visits across ~130 days with progressively worsening signals.

    Inter-visit gaps are: [30, 30, 30, 30, 10] days, so trajectory Signal 3
    (visit frequency) fires on visit 6 (latest gap 10 < avg 23.3 * 0.7).
    """
    base = datetime.now(timezone.utc) - timedelta(days=130)

    visits: list[Visit] = []

    # --- Visit 1 (day 0) — routine, fully normal ---------------------------
    visits.append(
        Visit(
            id=uuid.uuid4(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            visit_date=base + timedelta(days=0),
            raw_transcript=(
                "doctor: How have you been since the last visit?\n"
                "patient: Pretty good. Blood sugar steady, no real complaints."
            ),
            soap_note=_soap(
                subjective=(
                    "Routine follow-up for type 2 diabetes and hypertension. "
                    "Reports stable home glucose readings and good adherence "
                    "to current regimen. No new complaints."
                ),
                objective=(
                    "BP 128/82, HR 72, RR 16, SpO2 99%, weight 168 lbs. "
                    "Cardiopulmonary exam unremarkable."
                ),
                assessment=(
                    "Stable T2DM (E11.9) and essential hypertension (I10), "
                    "both well controlled on current therapy."
                ),
                plan=(
                    "Continue metformin 500 mg BID and lisinopril 10 mg daily. "
                    "Repeat HbA1c in three months. Routine follow-up in 30 days."
                ),
            ),
            anomalies=[],
            differentials=[
                {
                    "diagnosis": "Stable T2DM",
                    "confidence": 0.92,
                    "contributing_fields": ["assessment", "subjective"],
                }
            ],
            drift_flag=_drift(False, "no_significant_drift", 0.05),
            compliance_status="pass",
            compliance_notes=[],
            bias_flags=[],
            trajectory_score=None,
            trajectory_direction=None,
            trajectory_watch_zones=[],
            is_signed=True,
            signed_at=base + timedelta(days=0, hours=1),
        )
    )

    # --- Visit 2 (day 30) — still normal ------------------------------------
    visits.append(
        Visit(
            id=uuid.uuid4(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            visit_date=base + timedelta(days=30),
            raw_transcript=(
                "doctor: Any new symptoms?\n"
                "patient: Just an occasional mild headache, nothing major."
            ),
            soap_note=_soap(
                subjective=(
                    "Reports occasional mild morning headaches relieved by "
                    "acetaminophen. Otherwise feels well, sleeping normally."
                ),
                objective=(
                    "BP 132/84, HR 74, RR 16, SpO2 99%, weight 169 lbs. "
                    "Neurologic exam grossly normal."
                ),
                assessment=(
                    "T2DM and HTN remain controlled. Headaches likely "
                    "tension-type given pattern."
                ),
                plan=(
                    "Continue current medications. PRN acetaminophen for "
                    "headache. Return in 30 days or sooner if symptoms worsen."
                ),
            ),
            anomalies=[],
            differentials=[
                {
                    "diagnosis": "Tension-type headache",
                    "confidence": 0.71,
                    "contributing_fields": ["subjective"],
                }
            ],
            drift_flag=_drift(False, "no_significant_drift", 0.10),
            compliance_status="pass",
            compliance_notes=[],
            bias_flags=[],
            trajectory_score=None,
            trajectory_direction=None,
            trajectory_watch_zones=[],
            is_signed=True,
            signed_at=base + timedelta(days=30, hours=1),
        )
    )

    # --- Visit 3 (day 60) — FIRST DRIFT FLAG --------------------------------
    visits.append(
        Visit(
            id=uuid.uuid4(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            visit_date=base + timedelta(days=60),
            raw_transcript=(
                "doctor: How are you doing?\n"
                "patient: I'm tired all the time. I can't keep up with my "
                "grandkids, I feel exhausted and a little anxious."
            ),
            soap_note=_soap(
                subjective=(
                    "Reports persistent fatigue and difficulty keeping up "
                    "with daily activities. Describes feeling exhausted, "
                    "tired, and anxious. Denies fever, chest pain, "
                    "shortness of breath."
                ),
                objective=(
                    "BP 138/86, HR 78, RR 16, SpO2 98%, weight 170 lbs. "
                    "Affect mildly flat. Otherwise unremarkable exam."
                ),
                assessment=(
                    "T2DM and HTN at upper end of target. New fatigue with "
                    "anxious affect; consider screen for depression and "
                    "sleep disturbance."
                ),
                plan=(
                    "Order CBC, CMP, TSH, HbA1c. PHQ-9 at next visit. "
                    "Continue current medications. Return in 30 days."
                ),
            ),
            anomalies=[],
            differentials=[
                {
                    "diagnosis": "Adjustment disorder with anxious mood",
                    "confidence": 0.62,
                    "contributing_fields": ["subjective"],
                },
                {
                    "diagnosis": "Subclinical hypothyroidism",
                    "confidence": 0.41,
                    "contributing_fields": ["subjective", "objective"],
                },
            ],
            drift_flag=_drift(
                True, "increased_negative_affect", 0.32
            ),  # first flag
            compliance_status="pass",
            compliance_notes=[],
            bias_flags=[],
            trajectory_score=None,
            trajectory_direction=None,
            trajectory_watch_zones=[],
            is_signed=True,
            signed_at=base + timedelta(days=60, hours=1),
        )
    )

    # --- Visit 4 (day 90) — FIRST ANOMALY + DECLINING TRAJECTORY -----------
    visits.append(
        Visit(
            id=uuid.uuid4(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            visit_date=base + timedelta(days=90),
            raw_transcript=(
                "doctor: What brings you in today?\n"
                "patient: My chest has been hurting on and off. Sharp pain "
                "that comes when I walk up stairs."
            ),
            soap_note=_soap(
                subjective=(
                    "New onset intermittent chest pain over the past two "
                    "weeks. Sharp, exertional, lasting 1–2 minutes, relieved "
                    "by rest. Still tired and exhausted most days."
                ),
                objective=(
                    "BP 158/95 (elevated above target). HR 82, RR 18, "
                    "SpO2 98%. Cardiac exam: regular rhythm, no murmurs. "
                    "ECG: normal sinus, no acute changes."
                ),
                assessment=(
                    "Suspected stable angina in the setting of poorly "
                    "controlled HTN and T2DM. Atypical presentation must be "
                    "evaluated cardiologically."
                ),
                plan=(
                    "Increase lisinopril to 20 mg daily. Order lipid panel, "
                    "troponin, BNP. Refer to cardiology within two weeks. "
                    "Return in 30 days."
                ),
            ),
            anomalies=[
                _anomaly(
                    "medium",
                    "outlier_vital",
                    "BP 158/95 exceeds diabetic target (<130/80). "
                    "Sustained reading warrants treatment escalation.",
                    source_line=5,
                ),
            ],
            differentials=[
                {
                    "diagnosis": "Stable angina pectoris",
                    "confidence": 0.74,
                    "contributing_fields": ["subjective", "objective"],
                },
                {
                    "diagnosis": "Hypertensive urgency",
                    "confidence": 0.55,
                    "contributing_fields": ["objective", "assessment"],
                },
            ],
            drift_flag=_drift(True, "increased_pain_descriptors", 0.28),
            compliance_status="pass",
            compliance_notes=[],
            bias_flags=[],
            trajectory_score=-3.0,
            trajectory_direction="down",
            trajectory_watch_zones=[
                "Anomaly count trending up (0→0→1)",
                "Drift flagged in 2 of last 3 visits",
            ],
            is_signed=True,
            signed_at=base + timedelta(days=90, hours=1),
        )
    )

    # --- Visit 5 (day 120) — COMPLIANCE WARNINGS (3 HIPAA violations) ------
    visits.append(
        Visit(
            id=uuid.uuid4(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            visit_date=base + timedelta(days=120),
            raw_transcript=(
                "doctor: How is the chest pain?\n"
                "patient: It's worse. Now it hurts even when I'm sitting still. "
                "Hurts more at night."
            ),
            soap_note=_soap(
                subjective=(
                    # PII leak (HIPAA injection #1): patient name appears in note
                    "Maria Hernandez reports the chest pain has worsened. "
                    "Now occurring at rest, throbbing, worse at night. "
                    "Sharp burning radiating to the left arm. Sleep poor."
                ),
                objective=(
                    "BP 162/98, HR 88, RR 18, SpO2 97%. Cardiac auscultation "
                    "reveals an S4 gallop. Lungs clear."
                ),
                # Missing ICD-10 (HIPAA injection #2): assessment lacks code
                assessment=(
                    "Worsening exertional and now resting chest pain. "
                    "Possible unstable angina."
                ),
                # Missing disposition (HIPAA injection #3): plan lacks follow-up
                plan=(
                    "Add metoprolol succinate 25 mg daily. Continue all other "
                    "medications."
                ),
                source_lines=11,
            ),
            anomalies=[
                _anomaly(
                    "high",
                    "contradictory_symptom",
                    "Resting chest pain in a diabetic with HTN — must rule "
                    "out acute coronary syndrome before discharge.",
                    source_line=7,
                ),
                _anomaly(
                    "medium",
                    "outlier_vital",
                    "Persistent BP 162/98 despite increased lisinopril.",
                    source_line=5,
                ),
            ],
            differentials=[
                {
                    "diagnosis": "Unstable angina",
                    "confidence": 0.81,
                    "contributing_fields": [
                        "subjective",
                        "objective",
                        "assessment",
                    ],
                },
                {
                    "diagnosis": "Acute coronary syndrome",
                    "confidence": 0.68,
                    "contributing_fields": ["subjective", "objective"],
                },
            ],
            drift_flag=_drift(False, "no_significant_drift", 0.18),
            compliance_status="fail",
            compliance_notes=[
                _compliance(
                    "subjective",
                    "Patient identifier (full name) appears in the note body — "
                    "HIPAA minimum-necessary violation.",
                    "Replace 'Maria Hernandez' with 'the patient' or use a "
                    "redacted identifier.",
                ),
                _compliance(
                    "assessment",
                    "Assessment lacks an ICD-10 code suggestion.",
                    "Add I20.0 (unstable angina) or R07.9 (chest pain, "
                    "unspecified) to the assessment.",
                ),
                _compliance(
                    "plan",
                    "Plan does not include a follow-up disposition.",
                    "Document urgent cardiology referral, return precautions, "
                    "and timing of next visit.",
                ),
            ],
            bias_flags=[],
            trajectory_score=-5.0,
            trajectory_direction="down",
            trajectory_watch_zones=[
                "Anomaly count trending up (0→1→2)",
                "Chief complaint recurring: chest",
                "Chief complaint recurring: pain",
            ],
            is_signed=True,
            signed_at=base + timedelta(days=120, hours=1),
        )
    )

    # --- Visit 6 (day 130) — CLEAR DOWNWARD TRAJECTORY + 2 BIAS FLAGS ------
    visits.append(
        Visit(
            id=uuid.uuid4(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            visit_date=base + timedelta(days=130),
            raw_transcript=(
                "doctor: Why are you back so soon?\n"
                "patient: The chest pain is constant. It hurts to breathe. "
                "I'm scared."
            ),
            soap_note=_soap(
                subjective=(
                    # Bias injection #1 (socioeconomic): 'noncompliant'
                    # Bias injection #2 (age): 'elderly woman who is anxious'
                    "Elderly woman who is anxious presents with constant "
                    "chest pain, dyspnea, and palpitations. The patient is "
                    "noncompliant with her dietary recommendations. Pain is "
                    "burning, throbbing, radiates to the jaw and left arm."
                ),
                objective=(
                    "BP 174/104, HR 102, RR 22, SpO2 94% on room air. "
                    "Cardiac exam: tachycardic, S4 gallop, no murmurs. "
                    "ECG: ST depression in V4–V6. Troponin elevated at 0.18."
                ),
                assessment=(
                    "Non-ST elevation myocardial infarction (NSTEMI) in the "
                    "setting of poorly controlled HTN and T2DM. ICD-10: I21.4."
                ),
                plan=(
                    "Transfer to ED for emergent cardiac catheterization. "
                    "Continue current medications until handoff. Direct "
                    "admission to cardiology service. Family notified."
                ),
            ),
            anomalies=[
                _anomaly(
                    "high",
                    "outlier_vital",
                    "SpO2 94% on room air with tachypnea — possible "
                    "pulmonary edema, requires immediate evaluation.",
                    source_line=5,
                ),
                _anomaly(
                    "high",
                    "contradictory_symptom",
                    "Crescendo pattern from exertional to constant chest "
                    "pain over three visits — classic NSTEMI progression.",
                    source_line=8,
                ),
                _anomaly(
                    "medium",
                    "drug_interaction",
                    "Patient on metformin presenting with possible "
                    "cardiogenic shock — hold metformin to reduce lactic "
                    "acidosis risk pending contrast study.",
                    source_line=10,
                ),
            ],
            differentials=[
                {
                    "diagnosis": "NSTEMI",
                    "confidence": 0.94,
                    "contributing_fields": [
                        "subjective",
                        "objective",
                        "assessment",
                    ],
                },
                {
                    "diagnosis": "Acute decompensated heart failure",
                    "confidence": 0.66,
                    "contributing_fields": ["objective"],
                },
                {
                    "diagnosis": "Pulmonary embolism",
                    "confidence": 0.31,
                    "contributing_fields": ["objective"],
                },
            ],
            drift_flag=_drift(True, "increased_pain_descriptors", 0.41),
            compliance_status="warn",
            compliance_notes=[
                _compliance(
                    "plan",
                    "Plan should document time-stamped handoff to the "
                    "receiving cardiology team for medico-legal continuity.",
                    "Add explicit time of transfer and name of receiving "
                    "provider once known.",
                ),
            ],
            bias_flags=[
                _bias(
                    "the patient is noncompliant with her dietary recommendations",
                    "socioeconomic_bias",
                    "the patient reports challenges adhering to dietary "
                    "recommendations",
                ),
                _bias(
                    "Elderly woman who is anxious",
                    "age_bias",
                    "58-year-old patient who reports anxiety",
                ),
            ],
            trajectory_score=-7.0,
            trajectory_direction="down",
            trajectory_watch_zones=[
                "Anomaly count increasing 3 visits in a row (1→2→3)",
                "Drift flagged in 2 of last 3 visits",
                "Visit frequency increasing (latest gap 10d vs avg 23.3d)",
                "Chief complaint recurring: chest",
                "Chief complaint recurring: pain",
            ],
            is_signed=False,  # the demo opens on the unsigned visit 6
            signed_at=None,
        )
    )

    return visits


# ---------------------------------------------------------------------------
# Public entry point — callable from the CLI and from tests
# ---------------------------------------------------------------------------


async def seed() -> dict:
    """Idempotently seed the demo data and return a summary dict.

    Returns: ``{ "doctor_id", "doctor_email", "doctor_password",
                 "patient_id", "visit_ids", "trajectory" }``
    """
    async with AsyncSessionLocal() as session:
        # 1. Wipe any prior demo doctor (cascades to patients + visits).
        existing = await session.scalar(
            select(User).where(User.email == DEMO_EMAIL)
        )
        if existing is not None:
            log.info("removing prior demo doctor id=%s", existing.id)
            await session.execute(delete(User).where(User.id == existing.id))
            await session.commit()

        # 2. Create demo doctor with the cognitive-load counter already at 6 so
        #    the nudge fires on first dashboard load.
        today = datetime.now(timezone.utc).date()
        doctor = User(
            id=uuid.uuid4(),
            email=DEMO_EMAIL,
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name=DEMO_DOCTOR_NAME,
            role="doctor",
            session_count_today=6,
            last_session_date=today,
        )
        session.add(doctor)
        await session.flush()
        log.info("created demo doctor id=%s email=%s", doctor.id, doctor.email)

        # 3. Create demo patient.
        patient = Patient(
            id=uuid.uuid4(),
            full_name=DEMO_PATIENT_NAME,
            dob=DEMO_PATIENT_DOB,
            gender=DEMO_PATIENT_GENDER,
            doctor_id=doctor.id,
            allergies=DEMO_PATIENT_ALLERGIES,
            active_medications=DEMO_PATIENT_MEDS,
        )
        session.add(patient)
        await session.flush()
        log.info("created demo patient id=%s name=%s", patient.id, patient.full_name)

        # 4. Insert the 6 scripted visits.
        visits = _build_visits(patient_id=patient.id, doctor_id=doctor.id)
        for v in visits:
            session.add(v)
        await session.commit()
        log.info("inserted %d visits", len(visits))

        # 5. Sanity check: run the rule-based trajectory engine and confirm
        #    it independently agrees that the patient is declining.
        trajectory = await compute_trajectory(
            patient.id, drift_flag=None, db=session
        )
        if trajectory is None:
            log.warning("trajectory.compute returned None — unexpected for 6 visits")
        else:
            log.info(
                "trajectory direction=%s score=%.1f confidence=%d watch_zones=%d",
                trajectory.direction,
                trajectory.score,
                trajectory.confidence,
                len(trajectory.watch_zones),
            )
            if trajectory.direction != "down":
                log.warning(
                    "expected trajectory.direction='down' but got %r — "
                    "demo metrics may not match PRD §12",
                    trajectory.direction,
                )

        return {
            "doctor_id": str(doctor.id),
            "doctor_email": doctor.email,
            "doctor_password": DEMO_PASSWORD,
            "patient_id": str(patient.id),
            "visit_ids": [str(v.id) for v in visits],
            "trajectory": (
                trajectory.model_dump() if trajectory is not None else None
            ),
        }


async def _main() -> None:
    summary = await seed()
    log.info("seed complete")
    log.info(
        "  doctor:   %s / %s",
        summary["doctor_email"],
        summary["doctor_password"],
    )
    log.info("  patient:  %s", summary["patient_id"])
    log.info("  visits:   %d", len(summary["visit_ids"]))
    if summary["trajectory"] is not None:
        traj = summary["trajectory"]
        log.info(
            "  outcome:  trajectory=%s (score=%.1f, confidence=%d)",
            traj["direction"],
            traj["score"],
            traj["confidence"],
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
