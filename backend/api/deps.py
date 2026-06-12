"""Shared FastAPI dependencies: DB session + authenticated user resolution."""
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.constants import ADMIN_ROLE, DOCTOR_ROLE
from core.security import decode_access_token
from db.session import get_db
from models.user import User


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current User from the Authorization: Bearer <jwt> header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        # Don't echo the underlying JWT error (algorithm/signature/expiry detail)
        # back to the client; log it and return a generic message.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Token missing subject"
        )
    try:
        user_id = UUID(user_id_raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        ) from exc

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_user_sse(
    db: AsyncSession = Depends(get_db),
    token: Annotated[
        str | None,
        Query(description="JWT for SSE — EventSource cannot set Authorization headers"),
    ] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the current User from either ?token= query param (SSE/EventSource)
    or the standard Authorization: Bearer <jwt> header."""
    raw_token: str | None = None
    if token:
        raw_token = token
    elif authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", 1)[1].strip()

    if not raw_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    try:
        payload = decode_access_token(raw_token)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Token missing subject"
        )
    try:
        user_id = UUID(user_id_raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        ) from exc

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def require_doctor(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != DOCTOR_ROLE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Doctor role required"
        )
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != ADMIN_ROLE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    return user
