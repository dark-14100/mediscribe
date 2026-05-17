"""Phase 2 tests for /patients/* endpoints."""
import pytest

from tests.conftest import auth_header


_PAYLOAD = {
    "full_name": "John Doe",
    "dob": "1980-05-12",
    "gender": "male",
    "allergies": ["penicillin"],
    "active_medications": ["metformin"],
}


@pytest.mark.asyncio
async def test_create_patient_unauthenticated_returns_401(client):
    resp = await client.post("/patients", json=_PAYLOAD)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_patient_authenticated(client, doctor_user):
    resp = await client.post("/patients", json=_PAYLOAD, headers=auth_header(doctor_user))
    assert resp.status_code == 201
    body = resp.json()
    assert body["full_name"] == "John Doe"
    assert body["doctor_id"] == str(doctor_user.id)
    assert body["allergies"] == ["penicillin"]
    assert body["active_medications"] == ["metformin"]


@pytest.mark.asyncio
async def test_admin_cannot_create_patient(client, admin_user):
    resp = await client.post("/patients", json=_PAYLOAD, headers=auth_header(admin_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_patients_returns_only_my_patients(
    client, doctor_user, second_doctor
):
    # Each doctor creates one patient.
    r1 = await client.post(
        "/patients",
        json={**_PAYLOAD, "full_name": "Mine"},
        headers=auth_header(doctor_user),
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/patients",
        json={**_PAYLOAD, "full_name": "Theirs"},
        headers=auth_header(second_doctor),
    )
    assert r2.status_code == 201

    resp = await client.get("/patients", headers=auth_header(doctor_user))
    assert resp.status_code == 200
    names = [p["full_name"] for p in resp.json()]
    assert names == ["Mine"]


@pytest.mark.asyncio
async def test_list_patients_as_admin_returns_all(
    client, doctor_user, second_doctor, admin_user
):
    await client.post(
        "/patients",
        json={**_PAYLOAD, "full_name": "P1"},
        headers=auth_header(doctor_user),
    )
    await client.post(
        "/patients",
        json={**_PAYLOAD, "full_name": "P2"},
        headers=auth_header(second_doctor),
    )

    resp = await client.get("/patients", headers=auth_header(admin_user))
    assert resp.status_code == 200
    names = sorted(p["full_name"] for p in resp.json())
    assert names == ["P1", "P2"]


@pytest.mark.asyncio
async def test_get_patient_not_mine_returns_404(client, doctor_user, second_doctor):
    created = await client.post(
        "/patients", json=_PAYLOAD, headers=auth_header(second_doctor)
    )
    other_id = created.json()["id"]

    resp = await client.get(f"/patients/{other_id}", headers=auth_header(doctor_user))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_patient_mine_returns_200(client, doctor_user):
    created = await client.post(
        "/patients", json=_PAYLOAD, headers=auth_header(doctor_user)
    )
    pid = created.json()["id"]

    resp = await client.get(f"/patients/{pid}", headers=auth_header(doctor_user))
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


@pytest.mark.asyncio
async def test_summary_cache_miss_then_hit(client, doctor_user, fake_cache):
    created = await client.post(
        "/patients", json=_PAYLOAD, headers=auth_header(doctor_user)
    )
    pid = created.json()["id"]

    # First call → MISS → builds + caches.
    r1 = await client.get(
        f"/patients/{pid}/summary", headers=auth_header(doctor_user)
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["full_name"] == "John Doe"
    assert body["allergies"] == ["penicillin"]
    assert body["active_medications"] == ["metformin"]
    assert body["last_visit_dates"] == []
    assert body["trajectory_direction"] is None

    assert f"patient_summary:{pid}" in fake_cache._store

    # Second call → HIT → served from cache.
    r2 = await client.get(
        f"/patients/{pid}/summary", headers=auth_header(doctor_user)
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == pid


@pytest.mark.asyncio
async def test_summary_not_mine_returns_404(client, doctor_user, second_doctor):
    created = await client.post(
        "/patients", json=_PAYLOAD, headers=auth_header(second_doctor)
    )
    pid = created.json()["id"]

    resp = await client.get(
        f"/patients/{pid}/summary", headers=auth_header(doctor_user)
    )
    assert resp.status_code == 404
