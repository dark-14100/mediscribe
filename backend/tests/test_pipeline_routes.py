"""Tests for /pipeline/* routes.

These cover the *backend* concerns only:
* Auth + ownership enforcement.
* Orchestration order (which SSE events fire, in what order).
* Persistence of the assembled PipelinePayload to the visits table.
* 503 behaviour when an AI service is not yet implemented.

The AI services (transcription, soap_generator, anomaly_agent, ...) are
patched with simple fakes so we never need real Groq / sentence-transformers.
"""
from __future__ import annotations

import asyncio
import sys
import types
import uuid

import pytest

from schemas.pipeline import (
    AnomalyFlag,
    BiasFlag,
    ComplianceNote,
    ComplianceResult,
    Differential,
    DriftFlag,
    SOAPField,
    SOAPNote,
    TrajectoryResult,
    TranscriptLine,
)
from services.event_bus import get_event_bus
from tests.conftest import auth_header


# ---------------------------------------------------------------------------
# AI service stubs — installed into sys.modules so the pipeline route's
# importlib.import_module(...) calls resolve cleanly.
# ---------------------------------------------------------------------------


def _install_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_FAKE_TRANSCRIPT = [
    TranscriptLine(speaker="doctor", text="What brings you in?", line_index=1),
    TranscriptLine(speaker="patient", text="My head hurts.", line_index=2),
]

_FAKE_SOAP = SOAPNote(
    subjective=SOAPField(text="Headache.", source_lines=[2]),
    objective=SOAPField(text="No fever.", source_lines=[]),
    assessment=SOAPField(text="Tension headache.", source_lines=[]),
    plan=SOAPField(text="Ibuprofen.", source_lines=[]),
)


@pytest.fixture
def ai_services_installed(monkeypatch):
    """Install fake AI service modules for the duration of the test."""

    async def transcribe(audio_bytes: bytes):
        return _FAKE_TRANSCRIPT

    async def generate(transcript):
        return _FAKE_SOAP

    async def get_summaries(soap, patient_id):
        return ["2026-03-01: prior visit summary"]

    async def detect_anomaly(soap, history, meds):
        return [
            AnomalyFlag(
                severity="low",
                type="contradictory_symptom",
                description="benign",
                source_line=2,
            )
        ]

    async def diagnose(soap):
        return [
            Differential(
                diagnosis="Tension headache",
                confidence=0.8,
                contributing_fields=["subjective", "assessment"],
            )
        ]

    async def detect_drift(patient_id, transcript):
        return DriftFlag(
            flagged=False, direction="no_significant_drift", delta=0.05, threshold=0.25
        )

    async def check(soap):
        return ComplianceResult(
            status="pass",
            notes=[ComplianceNote(field="plan", issue="ok", suggestion="ok")],
        )

    async def review(soap):
        return [
            BiasFlag(
                phrase="overly anxious",
                type="gender_bias",
                suggested_rewrite="reports anxiety",
            )
        ]

    async def compute(patient_id, drift_flag, db):
        return TrajectoryResult(
            direction="stable",
            score=0.0,
            confidence=40,
            watch_zones=[],
            computed_from_visits=2,
        )

    _install_module("services.transcription", transcribe=transcribe)
    _install_module("services.soap_generator", generate=generate)
    _install_module("services.history_retrieval", get_summaries=get_summaries)
    _install_module("services.anomaly_agent", detect=detect_anomaly)
    _install_module("services.differential_agent", diagnose=diagnose)
    _install_module("services.drift_agent", detect=detect_drift)
    _install_module("services.compliance", check=check)
    _install_module("services.bias_review", review=review)
    _install_module("services.trajectory", compute=compute)
    yield
    for name in (
        "services.transcription",
        "services.soap_generator",
        "services.history_retrieval",
        "services.anomaly_agent",
        "services.differential_agent",
        "services.drift_agent",
        "services.compliance",
        "services.bias_review",
        "services.trajectory",
    ):
        sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_patient_and_visit(client, doctor) -> tuple[str, str]:
    pr = await client.post(
        "/patients",
        json={
            "full_name": "P",
            "dob": "1990-01-01",
            "gender": "female",
            "allergies": [],
            "active_medications": ["ibuprofen"],
        },
        headers=auth_header(doctor),
    )
    pid = pr.json()["id"]
    vr = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(doctor)
    )
    return pid, vr.json()["id"]


# ---------------------------------------------------------------------------
# /pipeline/transcribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_returns_503_when_service_missing(client, doctor_user):
    resp = await client.post(
        "/pipeline/transcribe",
        headers=auth_header(doctor_user),
        files={"audio": ("clip.webm", b"raw-bytes", "audio/webm")},
    )
    assert resp.status_code == 503
    assert "Transcription service" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_transcribe_returns_diarised_transcript(
    client, doctor_user, ai_services_installed
):
    """Conftest autouse fixture stubs out Celery's send_task globally."""
    _, vid = await _create_patient_and_visit(client, doctor_user)
    resp = await client.post(
        "/pipeline/transcribe",
        headers=auth_header(doctor_user),
        files={"audio": ("clip.webm", b"raw-bytes", "audio/webm")},
        params={"visit_id": vid},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["transcript"]) == 2
    assert body["transcript"][0]["speaker"] == "doctor"
    assert body["audio_upload_queued"] is True


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_audio(client, doctor_user):
    resp = await client.post(
        "/pipeline/transcribe",
        headers=auth_header(doctor_user),
        files={"audio": ("clip.webm", b"", "audio/webm")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /pipeline/run + SSE stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_503_when_soap_service_missing(client, doctor_user):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    resp = await client.post(
        "/pipeline/run",
        json={"visit_id": vid, "transcript": [t.model_dump() for t in _FAKE_TRANSCRIPT]},
        headers=auth_header(doctor_user),
    )
    assert resp.status_code == 503
    assert "SOAP generator" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_assembles_full_payload(
    client, doctor_user, ai_services_installed
):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    resp = await client.post(
        "/pipeline/run",
        json={"visit_id": vid, "transcript": [t.model_dump() for t in _FAKE_TRANSCRIPT]},
        headers=auth_header(doctor_user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["visit_id"] == vid
    assert body["soap_note"]["assessment"]["text"] == "Tension headache."
    assert len(body["anomalies"]) == 1
    assert body["differentials"][0]["diagnosis"] == "Tension headache"
    assert body["drift_flag"]["flagged"] is False
    assert body["compliance_status"] == "pass"
    assert len(body["bias_flags"]) == 1
    assert body["trajectory"]["direction"] == "stable"


@pytest.mark.asyncio
async def test_run_persists_payload_to_visit(
    client, doctor_user, ai_services_installed
):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    await client.post(
        "/pipeline/run",
        json={"visit_id": vid, "transcript": [t.model_dump() for t in _FAKE_TRANSCRIPT]},
        headers=auth_header(doctor_user),
    )

    fetched = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    assert fetched.status_code == 200
    v = fetched.json()
    assert v["soap_note"]["assessment"]["text"] == "Tension headache."
    assert v["compliance_status"] == "pass"
    assert v["trajectory_direction"] == "stable"
    assert v["raw_transcript"].startswith("[doctor]")


@pytest.mark.asyncio
async def test_run_other_doctors_visit_returns_404(
    client, doctor_user, second_doctor, ai_services_installed
):
    _, other_vid = await _create_patient_and_visit(client, second_doctor)
    resp = await client.post(
        "/pipeline/run",
        json={"visit_id": other_vid, "transcript": []},
        headers=auth_header(doctor_user),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_on_signed_visit_returns_409(
    client, doctor_user, ai_services_installed
):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    sign = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert sign.status_code == 200

    resp = await client.post(
        "/pipeline/run",
        json={"visit_id": vid, "transcript": []},
        headers=auth_header(doctor_user),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_run_publishes_events_in_order(
    client, doctor_user, ai_services_installed
):
    """SSE subscriber receives soap, anomalies, differentials, drift, compliance, bias, trajectory."""
    _, vid = await _create_patient_and_visit(client, doctor_user)
    bus = get_event_bus()
    received: list[str] = []

    async def subscriber():
        async for event in bus.subscribe(vid):
            received.append(event.name)

    sub_task = asyncio.create_task(subscriber())

    # Wait until subscription is active before starting the run.
    for _ in range(20):
        if bus.subscriber_count(vid) >= 1:
            break
        await asyncio.sleep(0.01)
    assert bus.subscriber_count(vid) == 1

    resp = await client.post(
        "/pipeline/run",
        json={"visit_id": vid, "transcript": [t.model_dump() for t in _FAKE_TRANSCRIPT]},
        headers=auth_header(doctor_user),
    )
    assert resp.status_code == 200
    await asyncio.wait_for(sub_task, timeout=2.0)

    # SOAP first, anomalies/differentials/drift after Step 4, then compliance,
    # then bias + trajectory, then pipeline_done.
    assert received[0] == "soap_ready"
    assert "anomalies_ready" in received
    assert "differentials_ready" in received
    assert "drift_ready" in received
    assert received.index("compliance_ready") > received.index("anomalies_ready")
    assert received.index("bias_ready") > received.index("compliance_ready")
    assert received[-1] == "pipeline_done"


@pytest.mark.asyncio
async def test_stream_endpoint_requires_visit_ownership(
    client, doctor_user, second_doctor
):
    # Visit owned by second_doctor
    pr = await client.post(
        "/patients",
        json={
            "full_name": "X",
            "dob": "1990-01-01",
            "gender": "male",
            "allergies": [],
            "active_medications": [],
        },
        headers=auth_header(second_doctor),
    )
    pid = pr.json()["id"]
    vr = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(second_doctor)
    )
    other_vid = vr.json()["id"]

    resp = await client.get(
        f"/pipeline/stream/{other_vid}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /pipeline/run-status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_status_returns_persisted_payload(
    client, doctor_user, ai_services_installed
):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    await client.post(
        "/pipeline/run",
        json={"visit_id": vid, "transcript": []},
        headers=auth_header(doctor_user),
    )
    resp = await client.get(
        f"/pipeline/run-status/{vid}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["visit_id"] == vid
    assert body["soap_note"]["subjective"]["text"] == "Headache."


@pytest.mark.asyncio
async def test_run_status_unknown_visit_returns_404(client, doctor_user):
    fake = str(uuid.uuid4())
    resp = await client.get(
        f"/pipeline/run-status/{fake}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 404
