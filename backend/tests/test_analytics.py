"""Tests for /analytics/* endpoints."""
import pytest

from tests.conftest import auth_header


_PATIENT_PAYLOAD = {
    "full_name": "Analytics Patient",
    "dob": "1985-01-01",
    "gender": "female",
    "allergies": [],
    "active_medications": [],
}


# ---------------------------------------------------------------------------
# /analytics/trajectory/{patient_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trajectory_returns_404_for_unknown_patient(client, doctor_user):
    import uuid as _uuid

    bogus = str(_uuid.uuid4())
    resp = await client.get(
        f"/analytics/trajectory/{bogus}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trajectory_returns_404_for_other_doctors_patient(
    client, doctor_user, second_doctor
):
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(second_doctor)
    )
    pid = pr.json()["id"]
    resp = await client.get(
        f"/analytics/trajectory/{pid}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trajectory_returns_null_for_patient_without_visits(
    client, doctor_user
):
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(doctor_user)
    )
    pid = pr.json()["id"]
    resp = await client.get(
        f"/analytics/trajectory/{pid}", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_trajectory_unauthenticated_returns_401(client):
    import uuid as _uuid

    resp = await client.get(f"/analytics/trajectory/{_uuid.uuid4()}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /analytics/load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_initial_state_is_zero(client, doctor_user):
    resp = await client.get("/analytics/load", headers=auth_header(doctor_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_count"] == 0
    assert body["threshold"] == 6
    assert body["threshold_exceeded"] is False


@pytest.mark.asyncio
async def test_load_increments_with_each_created_visit(client, doctor_user):
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(doctor_user)
    )
    pid = pr.json()["id"]

    for _ in range(3):
        await client.post(
            "/visits", json={"patient_id": pid}, headers=auth_header(doctor_user)
        )

    resp = await client.get("/analytics/load", headers=auth_header(doctor_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_count"] == 3
    assert body["threshold_exceeded"] is False


@pytest.mark.asyncio
async def test_load_threshold_exceeded_after_six_sessions(
    client, doctor_user
):
    pr = await client.post(
        "/patients", json=_PATIENT_PAYLOAD, headers=auth_header(doctor_user)
    )
    pid = pr.json()["id"]
    for _ in range(6):
        await client.post(
            "/visits", json={"patient_id": pid}, headers=auth_header(doctor_user)
        )
    resp = await client.get("/analytics/load", headers=auth_header(doctor_user))
    body = resp.json()
    assert body["session_count"] == 6
    assert body["threshold_exceeded"] is True


@pytest.mark.asyncio
async def test_load_unauthenticated_returns_401(client):
    resp = await client.get("/analytics/load")
    assert resp.status_code == 401
