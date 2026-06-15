"""Tests for EHR write-back: FHIR mapping (pure) + POST /notes/ehr-export."""
import base64

import pytest

from tests.conftest import auth_header

_PATIENT_PAYLOAD = {
    "full_name": "Ehr Patient",
    "dob": "1970-02-03",
    "gender": "male",
    "allergies": [],
    "active_medications": [],
}

_SOAP_BODY = {
    "soap_note": {
        "subjective": {"text": "Patient reports a cough.", "source_lines": [1]},
        "objective": {"text": "Lungs clear.", "source_lines": [2]},
        "assessment": {"text": "Viral URI.", "source_lines": [3]},
        "plan": {"text": "Supportive care.", "source_lines": [4]},
    },
    "soap_audit_trail": {},
}


# --- Pure mapping tests (no app / network) ---------------------------------


def test_build_document_reference_maps_loinc_and_text():
    from datetime import datetime, timezone

    from services.ehr_export import build_document_reference

    sections = {
        "chief_complaint": {"text": "Chest tightness."},
        "assessment": {"text": "Stable angina."},
    }
    doc = build_document_reference(
        note_type="hp",
        sections=sections,
        patient_reference="Patient/123",
        doctor_name="Dr. Demo",
        signed_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )
    assert doc["resourceType"] == "DocumentReference"
    assert doc["status"] == "current"
    assert doc["type"]["coding"][0]["code"] == "34117-2"
    assert doc["subject"]["reference"] == "Patient/123"
    assert doc["author"][0]["display"] == "Dr. Demo"
    decoded = base64.b64decode(doc["content"][0]["attachment"]["data"]).decode()
    assert "Chief Complaint:" in decoded
    assert "Stable angina." in decoded
    # No language passed -> attachment carries no language tag.
    assert "language" not in doc["content"][0]["attachment"]


def test_build_document_reference_sets_attachment_language():
    from datetime import datetime, timezone

    from services.ehr_export import build_document_reference

    doc = build_document_reference(
        note_type="soap",
        sections={"subjective": {"text": "Dolor en el pecho."}},
        patient_reference="Patient/1",
        doctor_name="Dra. Demo",
        signed_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        language="es",
    )
    assert doc["content"][0]["attachment"]["language"] == "es"


def test_assemble_note_text_skips_empty_sections_and_orders_by_template():
    from services.ehr_export import assemble_note_text

    text = assemble_note_text(
        "soap",
        {
            "subjective": {"text": "S text."},
            "objective": {"text": ""},
            "assessment": {"text": "A text."},
            "plan": {"text": "P text."},
        },
    )
    assert "Objective:" not in text  # empty section dropped
    assert text.index("Subjective:") < text.index("Assessment:") < text.index("Plan:")


# --- Endpoint tests --------------------------------------------------------


async def _signed_visit(client, doctor) -> str:
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(doctor)
    )
    pid = pr.json()["id"]
    vr = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(doctor)
    )
    vid = vr.json()["id"]
    await client.post(f"/notes/save/{vid}", json=_SOAP_BODY, headers=auth_header(doctor))
    await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor))
    return vid


@pytest.mark.asyncio
async def test_ehr_export_disabled_by_default_returns_403(client, doctor_user):
    vid = await _signed_visit(client, doctor_user)
    resp = await client.post(
        f"/notes/ehr-export/{vid}", json={}, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ehr_export_requires_signed_note(client, doctor_user, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "EHR_EXPORT_MODE", "manual")
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(doctor_user)
    )
    pid = pr.json()["id"]
    vr = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(doctor_user)
    )
    vid = vr.json()["id"]
    resp = await client.post(
        f"/notes/ehr-export/{vid}", json={}, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_ehr_export_files_and_persists(client, doctor_user, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "EHR_EXPORT_MODE", "manual")

    async def fake_export(**kwargs):
        return {
            "document_reference_id": "DocumentReference/999",
            "patient_fhir_id": "Patient/42",
            "fhir_base_url": "https://hapi.fhir.org/baseR4",
        }

    monkeypatch.setattr("api.routes.notes.export_note", fake_export)

    vid = await _signed_visit(client, doctor_user)
    resp = await client.post(
        f"/notes/ehr-export/{vid}", json={}, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "filed"
    assert body["document_reference_id"] == "DocumentReference/999"

    # Persisted into the audit trail.
    fetched = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    ex = fetched.json()["soap_audit_trail"]["ehr_export"]
    assert ex["status"] == "filed"
    assert ex["document_reference_id"] == "DocumentReference/999"


@pytest.mark.asyncio
async def test_ehr_export_idempotent_unless_forced(client, doctor_user, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "EHR_EXPORT_MODE", "manual")
    calls = {"n": 0}

    async def fake_export(**kwargs):
        calls["n"] += 1
        return {
            "document_reference_id": f"DocumentReference/{calls['n']}",
            "patient_fhir_id": "Patient/42",
            "fhir_base_url": "https://hapi.fhir.org/baseR4",
        }

    monkeypatch.setattr("api.routes.notes.export_note", fake_export)

    vid = await _signed_visit(client, doctor_user)
    first = await client.post(
        f"/notes/ehr-export/{vid}", json={}, headers=auth_header(doctor_user)
    )
    assert first.json()["document_reference_id"] == "DocumentReference/1"

    # Second call without force is a no-op (returns the existing record).
    again = await client.post(
        f"/notes/ehr-export/{vid}", json={}, headers=auth_header(doctor_user)
    )
    assert again.json()["document_reference_id"] == "DocumentReference/1"
    assert calls["n"] == 1

    # With force it re-files.
    forced = await client.post(
        f"/notes/ehr-export/{vid}", json={"force": True}, headers=auth_header(doctor_user)
    )
    assert forced.json()["document_reference_id"] == "DocumentReference/2"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_ehr_export_failure_returns_502_and_records(client, doctor_user, monkeypatch):
    from core.config import settings
    from services.ehr_export import EhrExportError

    monkeypatch.setattr(settings, "EHR_EXPORT_MODE", "manual")

    async def boom(**kwargs):
        raise EhrExportError("FHIR server unreachable.")

    monkeypatch.setattr("api.routes.notes.export_note", boom)

    vid = await _signed_visit(client, doctor_user)
    resp = await client.post(
        f"/notes/ehr-export/{vid}", json={}, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 502

    fetched = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    ex = fetched.json()["soap_audit_trail"]["ehr_export"]
    assert ex["status"] == "failed"
    assert "unreachable" in (ex["error"] or "")
