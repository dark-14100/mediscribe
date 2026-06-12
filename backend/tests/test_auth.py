"""Phase 1 acceptance tests for POST /auth/register and POST /auth/login."""
import pytest

from core.security import decode_access_token


@pytest.mark.asyncio
async def test_register_creates_user(client):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "doc@example.com",
            "password": "supersecret123",
            "full_name": "Dr. Test",
            "role": "doctor",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "doc@example.com"
    assert body["full_name"] == "Dr. Test"
    assert body["role"] == "doctor"
    assert "id" in body
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_register_rejects_short_password(client):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "weak@example.com",
            "password": "short",
            "full_name": "Dr. Weak",
            "role": "doctor",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_invalid_role(client):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "nope@example.com",
            "password": "password123",
            "full_name": "Dr. Nope",
            "role": "patient",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_admin_self_assignment(client):
    """Public registration must not let a caller self-assign an elevated role."""
    resp = await client.post(
        "/auth/register",
        json={
            "email": "sneaky@example.com",
            "password": "password123",
            "full_name": "Dr. Sneaky",
            "role": "admin",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client):
    payload = {
        "email": "dup@example.com",
        "password": "password123",
        "full_name": "Dr. Dup",
        "role": "doctor",
    }
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_login_returns_valid_jwt(client):
    await client.post(
        "/auth/register",
        json={
            "email": "login@example.com",
            "password": "password123",
            "full_name": "Dr. Login",
            "role": "doctor",
        },
    )
    resp = await client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    token = body["access_token"]
    assert isinstance(token, str) and len(token) > 20

    payload = decode_access_token(token)
    assert payload["role"] == "doctor"
    assert "sub" in payload
    assert "exp" in payload


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client):
    await client.post(
        "/auth/register",
        json={
            "email": "wrongpw@example.com",
            "password": "password123",
            "full_name": "Dr. WP",
            "role": "doctor",
        },
    )
    resp = await client.post(
        "/auth/login",
        json={"email": "wrongpw@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user_returns_401(client):
    resp = await client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "anything12345"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
