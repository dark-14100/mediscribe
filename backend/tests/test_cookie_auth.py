"""Cookie-based auth + CSRF tests.

Covers the WP3 migration: login sets HttpOnly auth + readable CSRF cookies,
the cookie alone authenticates subsequent requests (no Authorization header),
state-changing requests require a matching CSRF header, and logout clears the
cookies.
"""
import pytest

_DOCTOR = {
    "email": "cookie.doc@example.com",
    "password": "password123",
    "full_name": "Dr. Cookie",
    "role": "doctor",
}
_PATIENT = {
    "full_name": "P Cookie",
    "dob": "1990-01-01",
    "gender": "female",
    "allergies": [],
    "active_medications": [],
}


async def _register_and_login(client):
    await client.post("/auth/register", json=_DOCTOR)
    resp = await client.post(
        "/auth/login",
        json={"email": _DOCTOR["email"], "password": _DOCTOR["password"]},
    )
    assert resp.status_code == 200, resp.text
    return resp


@pytest.mark.asyncio
async def test_login_sets_cookies_and_authenticates_me(client):
    resp = await _register_and_login(client)
    assert "access_token" in resp.cookies
    assert "csrf_token" in resp.cookies

    # No Authorization header — the cookie alone must authenticate /auth/me.
    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == _DOCTOR["email"]


@pytest.mark.asyncio
async def test_cookie_mutation_requires_csrf(client):
    await _register_and_login(client)

    # Cookie present, no CSRF header -> blocked.
    blocked = await client.post("/patients", json=_PATIENT)
    assert blocked.status_code == 403

    # Echo the CSRF cookie back in the header -> allowed.
    csrf = client.cookies.get("csrf_token")
    allowed = await client.post(
        "/patients", json=_PATIENT, headers={"X-CSRF-Token": csrf}
    )
    assert allowed.status_code == 201


@pytest.mark.asyncio
async def test_csrf_endpoint_returns_cookie_token(client):
    await _register_and_login(client)
    cookie_token = client.cookies.get("csrf_token")

    resp = await client.get("/auth/csrf")
    assert resp.status_code == 200
    assert resp.json()["csrf_token"] == cookie_token


@pytest.mark.asyncio
async def test_logout_clears_cookies(client):
    await _register_and_login(client)

    out = await client.post("/auth/logout")
    assert out.status_code == 204

    me = await client.get("/auth/me")
    assert me.status_code == 401