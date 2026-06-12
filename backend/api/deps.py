"""Shared FastAPI dependencies: DB session + authenticated user resolution."""
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.constants import ADMIN_ROLE, DOCTOR_ROLE
from core.cookies import ACCESS_COOKIE
from core.security import decode_access_token
from db.session import get_db
from models.user import User


def _extract_token(request: Request, authorization: str | None) -> str | None:
    """Pull the JWT from the Authorization header (API clients) or, failing
    that, the HttpOnly access-token cookie (browser SPA / EventSource)."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return request.cookies.get(ACCESS_COOKIE)


async def _user_from_token(token: str | None, db: AsyncSession) -> User:
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
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


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current User from the Authorization header or auth cookie."""
    return await _user_from_token(_extract_token(request, authorization), db)


async def get_current_user_sse(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the current User for SSE/EventSource.

    EventSource cannot set an Authorization header, so browsers authenticate via
    the HttpOnly cookie (sent automatically with ``withCredentials``). The
    Authorization header is still accepted for non-browser clients."""
    return await _user_from_token(_extract_token(request, authorization), db)


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
