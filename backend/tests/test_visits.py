"""Phase 2 tests for /visits/* endpoints."""
import pytest

from tests.conftest import auth_header


_PATIENT_PAYLOAD = {
    "full_name": "Jane Patient",
    "dob": "1990-01-01",
    "gender": "female",
    "allergies": [],
    "active_medications": [],
}


async def _create_patient(client, user) -> str:
    resp = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(user)
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_create_visit_unauthenticated_returns_401(client, doctor_user):
    pid = await _create_patient(client, doctor_user)
    resp = await client.post("/visits", json={"patient_id": pid})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_visit_for_my_patient(client, doctor_user):
    pid = await _create_patient(client, doctor_user)
    resp = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(doctor_user)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["patient_id"] == pid
    assert body["doctor_id"] == str(doctor_user.id)
    assert body["is_signed"] is False
    assert body["soap_note"] == {}
    assert body["anomalies"] == []


@pytest.mark.asyncio
async def test_create_visit_for_other_doctors_patient_returns_404(
    client, doctor_user, second_doctor
):
    other_pid = await _create_patient(client, second_doctor)
    resp = await client.post(
        "/visits",
        json={"patient_id": other_pid},
        headers=auth_header(doctor_user),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_visit_mine(client, doctor_user):
    pid = await _create_patient(client, doctor_user)
    created = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(doctor_user)
    )
    vid = created.json()["id"]

    resp = await client.get(f"/visits/{vid}", headers=auth_header(doctor_user))
    assert resp.status_code == 200
    assert resp.json()["id"] == vid


@pytest.mark.asyncio
async def test_get_visit_not_mine_returns_404(client, doctor_user, second_doctor):
    other_pid = await _create_patient(client, second_doctor)
    created = await client.post(
        "/visits",
        json={"patient_id": other_pid},
        headers=auth_header(second_doctor),
    )
    other_vid = created.json()["id"]

    resp = await client.get(f"/visits/{other_vid}", headers=auth_header(doctor_user))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_patient_visits_newest_first(client, doctor_user):
    pid = await _create_patient(client, doctor_user)
    ids = []
    for _ in range(3):
        r = await client.post(
            "/visits", json={"patient_id": pid}, headers=auth_header(doctor_user)
        )
        ids.append(r.json()["id"])

    resp = await client.get(
        f"/visits/patient/{pid}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    returned_ids = [v["id"] for v in body]
    # Newest first, so the last-created visit comes first.
    assert returned_ids[0] == ids[-1]


@pytest.mark.asyncio
async def test_list_patient_visits_not_mine_returns_404(
    client, doctor_user, second_doctor
):
    other_pid = await _create_patient(client, second_doctor)
    resp = await client.get(
        f"/visits/patient/{other_pid}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_read_any_visit(client, doctor_user, admin_user):
    pid = await _create_patient(client, doctor_user)
    created = await client.post(
        "/visits", json={"patient_id": pid}, headers=auth_header(doctor_user)
    )
    vid = created.json()["id"]

    resp = await client.get(f"/visits/{vid}", headers=auth_header(admin_user))
    assert resp.status_code == 200
