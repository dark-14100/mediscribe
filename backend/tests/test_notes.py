"""Tests for POST /notes/save and POST /notes/sign."""
import pytest

from tests.conftest import auth_header

_PATIENT_PAYLOAD = {
    "full_name": "Note Patient",
    "dob": "1985-06-15",
    "gender": "female",
    "allergies": [],
    "active_medications": [],
}

_SOAP_BODY = {
    "soap_note": {
        "subjective": {"text": "Patient reports a headache.", "source_lines": [1]},
        "objective": {"text": "BP 120/80, T 98.6F.", "source_lines": [3]},
        "assessment": {"text": "Tension headache.", "source_lines": [4]},
        "plan": {"text": "Ibuprofen 400mg, follow-up in 1 week.", "source_lines": [5]},
    },
    "soap_audit_trail": {},
    "doctor_modified_fields": ["assessment"],
}


async def _create_patient_and_visit(client, doctor) -> tuple[str, str]:
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(doctor)
    )
    pid = pr.json()["id"]
    vr = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(doctor)
    )
    return pid, vr.json()["id"]


@pytest.mark.asyncio
async def test_save_note_persists_soap(client, doctor_user):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    resp = await client.post(
        f"/notes/save/{vid}", json=_SOAP_BODY, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["soap_note"]["assessment"]["text"] == "Tension headache."
    assert "doctor_modified_fields" in body["soap_audit_trail"]


@pytest.mark.asyncio
async def test_save_note_persists_coding_decisions(client, doctor_user):
    """Phase B: the doctor's accept/edit/dismiss choices land in the audit trail
    and survive into the signed record."""
    _, vid = await _create_patient_and_visit(client, doctor_user)
    body = {
        **_SOAP_BODY,
        "coding_decisions": {
            "accepted": [
                {
                    "system": "ICD-10",
                    "code": "G44.209",
                    "description": "Tension-type headache",
                    "origin": "edited",
                    "source_key": "ICD-10:R51",
                },
                {"system": "CPT", "code": "99213", "origin": "manual"},
            ],
            "dismissed": ["CPT:93000"],
        },
    }
    resp = await client.post(
        f"/notes/save/{vid}", json=body, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200
    trail = resp.json()["soap_audit_trail"]
    decisions = trail["coding_decisions"]
    assert decisions["dismissed"] == ["CPT:93000"]
    assert {a["code"] for a in decisions["accepted"]} == {"G44.209", "99213"}
    edited = next(a for a in decisions["accepted"] if a["code"] == "G44.209")
    assert edited["origin"] == "edited"
    assert edited["source_key"] == "ICD-10:R51"

    # Sign and confirm the decisions persist on the locked record.
    sign = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert sign.status_code == 200
    fetched = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    assert fetched.json()["soap_audit_trail"]["coding_decisions"]["dismissed"] == [
        "CPT:93000"
    ]


@pytest.mark.asyncio
async def test_save_note_persists_hp_note_sections(client, doctor_user):
    """A non-SOAP note type round-trips its own sections + note_type."""
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(doctor_user)
    )
    pid = pr.json()["id"]
    vr = await client.post(
        "/visits",
        json={"patient_id": pid, "note_type": "hp"},
        headers=auth_header(doctor_user),
    )
    assert vr.json()["note_type"] == "hp"
    vid = vr.json()["id"]

    body = {
        "note_type": "hp",
        "note_sections": {
            "chief_complaint": {"text": "Headache", "source_lines": [1]},
            "hpi": {"text": "Three days, throbbing", "source_lines": [2]},
            "assessment": {"text": "Tension headache", "source_lines": [4]},
            "plan": {"text": "Ibuprofen", "source_lines": [5]},
        },
        "doctor_modified_fields": ["assessment"],
    }
    resp = await client.post(
        f"/notes/save/{vid}", json=body, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200
    saved = resp.json()
    assert saved["note_type"] == "hp"
    assert saved["soap_note"]["chief_complaint"]["text"] == "Headache"
    assert saved["soap_note"]["hpi"]["text"] == "Three days, throbbing"

    # Reload confirms the note type and sections survived persistence.
    fetched = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    assert fetched.json()["note_type"] == "hp"
    assert fetched.json()["soap_note"]["assessment"]["text"] == "Tension headache"


@pytest.mark.asyncio
async def test_save_note_rejects_invalid_code_system(client, doctor_user):
    """An unknown code system is rejected by schema validation (422)."""
    _, vid = await _create_patient_and_visit(client, doctor_user)
    body = {
        **_SOAP_BODY,
        "coding_decisions": {
            "accepted": [{"system": "NOT-A-SYSTEM", "code": "X", "origin": "manual"}],
            "dismissed": [],
        },
    }
    resp = await client.post(
        f"/notes/save/{vid}", json=body, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_note_invalidates_summary_cache(client, doctor_user, fake_cache):
    pid, vid = await _create_patient_and_visit(client, doctor_user)
    # Prime the cache by hitting /summary once.
    await client.get(f"/patients/{pid}/summary", headers=auth_header(doctor_user))
    assert f"patient_summary:{pid}" in fake_cache._store

    resp = await client.post(
        f"/notes/save/{vid}", json=_SOAP_BODY, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200
    assert f"patient_summary:{pid}" not in fake_cache._store


@pytest.mark.asyncio
async def test_save_note_other_doctor_returns_404(
    client, doctor_user, second_doctor
):
    _, vid = await _create_patient_and_visit(client, second_doctor)
    resp = await client.post(
        f"/notes/save/{vid}", json=_SOAP_BODY, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_save_note_unauthenticated_returns_401(client, doctor_user):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    resp = await client.post(f"/notes/save/{vid}", json=_SOAP_BODY)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sign_note_flips_is_signed(client, doctor_user):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    resp = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_signed"] is True
    assert body["signed_at"] is not None


@pytest.mark.asyncio
async def test_sign_twice_returns_409(client, doctor_user):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    first = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert first.status_code == 200
    second = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_save_after_sign_returns_409(client, doctor_user):
    _, vid = await _create_patient_and_visit(client, doctor_user)
    sign = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert sign.status_code == 200
    save = await client.post(
        f"/notes/save/{vid}", json=_SOAP_BODY, headers=auth_header(doctor_user)
    )
    assert save.status_code == 409


# --- Grounding enforce gate (Phase C) --------------------------------------

_UNGROUNDED = {
    "status": "ungrounded",
    "confidence": 0.2,
    "checked_with": "rules",
    "fields": [
        {
            "field": "assessment",
            "status": "ungrounded",
            "confidence": 0.1,
            "cited_lines_valid": True,
            "unsupported_claims": [
                {
                    "field": "assessment",
                    "text": "Tension headache.",
                    "status": "ungrounded",
                    "confidence": 0.1,
                    "cited_lines": [4],
                    "issue": "Cited lines don't support this.",
                }
            ],
        }
    ],
}

_GROUNDED = {
    "status": "grounded",
    "confidence": 1.0,
    "checked_with": "rules",
    "fields": [
        {
            "field": "assessment",
            "status": "grounded",
            "confidence": 1.0,
            "cited_lines_valid": True,
            "unsupported_claims": [],
        }
    ],
}


async def _seed_grounding(client, doctor, vid, grounding) -> None:
    body = {**_SOAP_BODY, "soap_audit_trail": {"grounding": grounding}}
    resp = await client.post(
        f"/notes/save/{vid}", json=body, headers=auth_header(doctor)
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enforce_blocks_unacknowledged_ungrounded(
    client, doctor_user, monkeypatch
):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_MODE", "enforce")
    _, vid = await _create_patient_and_visit(client, doctor_user)
    await _seed_grounding(client, doctor_user, vid, _UNGROUNDED)

    resp = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert resp.status_code == 412
    assert "assessment" in resp.json()["detail"]["flagged_fields"]

    visit = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    assert visit.json()["is_signed"] is False


@pytest.mark.asyncio
async def test_enforce_signs_with_acknowledgement(client, doctor_user, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_MODE", "enforce")
    _, vid = await _create_patient_and_visit(client, doctor_user)
    await _seed_grounding(client, doctor_user, vid, _UNGROUNDED)

    resp = await client.post(
        f"/notes/sign/{vid}",
        json={"acknowledged": True},
        headers=auth_header(doctor_user),
    )
    assert resp.status_code == 200
    assert resp.json()["is_signed"] is True

    visit = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    ack = visit.json()["soap_audit_trail"]["grounding_ack"]
    assert ack["by"] == str(doctor_user.id)
    assert "assessment" in ack["flagged_fields"]


@pytest.mark.asyncio
async def test_enforce_signs_when_all_grounded(client, doctor_user, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_MODE", "enforce")
    _, vid = await _create_patient_and_visit(client, doctor_user)
    await _seed_grounding(client, doctor_user, vid, _GROUNDED)

    resp = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert resp.status_code == 200
    assert resp.json()["is_signed"] is True


@pytest.mark.asyncio
async def test_warn_mode_signs_despite_ungrounded(client, doctor_user, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_MODE", "warn")
    _, vid = await _create_patient_and_visit(client, doctor_user)
    await _seed_grounding(client, doctor_user, vid, _UNGROUNDED)

    resp = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert resp.status_code == 200  # warn never blocks


@pytest.mark.asyncio
async def test_enforce_fail_closed_when_grounding_missing(
    client, doctor_user, monkeypatch
):
    from core.config import settings

    monkeypatch.setattr(settings, "GROUNDING_MODE", "enforce")
    _, vid = await _create_patient_and_visit(client, doctor_user)
    # No grounding seeded — a missing check must not silently bypass the gate.
    resp = await client.post(f"/notes/sign/{vid}", headers=auth_header(doctor_user))
    assert resp.status_code == 412
