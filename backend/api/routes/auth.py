"""Auth routes: POST /auth/register, POST /auth/login, GET /auth/me."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.config import settings
from core.constants import DOCTOR_ROLE
from core.cookies import (
    CSRF_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
    set_csrf_cookie,
)
from core.ratelimit import limiter
from core.security import (
    create_access_token,
    generate_csrf_token,
    hash_password,
    verify_password,
)
from db.session import get_db
from models.user import User
from schemas.user import Token, UserCreate, UserLogin, UserRead

log = logging.getLogger("medscribe.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(
    request: Request,
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    # Public registration may only create doctors. Elevated roles (admin) bypass
    # tenant isolation and must be provisioned out-of-band (seed/migration/CLI),
    # never self-assigned through an unauthenticated endpoint.
    if payload.role != DOCTOR_ROLE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Cannot self-register with an elevated role",
        )

    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=DOCTOR_ROLE,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("[auth] registered user_id=%s role=%s", user.id, user.role)
    return user


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request,
    payload: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Token:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        # Use the same message for both branches to avoid leaking which one failed.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    token = create_access_token(subject=str(user.id), role=user.role)
    # Set the session in an HttpOnly cookie (browser SPA) + a readable CSRF
    # companion cookie. The token is still returned in the body for non-browser
    # API clients that authenticate with the Authorization header.
    set_auth_cookies(response, token, generate_csrf_token())
    log.info("[auth] login user_id=%s", user.id)
    return Token(access_token=token, token_type="bearer")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    """Clear the auth + CSRF cookies. Safe to call without a valid session."""
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.get("/csrf")
async def csrf(request: Request, response: Response) -> dict[str, str]:
    """Return the current CSRF token for the double-submit defence.

    A SPA on a different origin can't read the cross-site CSRF cookie via
    document.cookie, so it fetches the token here (the cookie is sent with the
    request automatically) and echoes it back in the X-CSRF-Token header on
    state-changing requests.
    """
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        token = generate_csrf_token()
        set_csrf_cookie(response, token)
    return {"csrf_token": token}


@router.get("/me", response_model=UserRead)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the currently authenticated user's profile."""
    return user
