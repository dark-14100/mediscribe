"""Auth cookie helpers — names, security attributes, and set/clear.

Centralises how the access-token and CSRF cookies are written so the login
route, logout route, and CSRF middleware all agree on names and attributes.

* The **access token** cookie is ``HttpOnly`` so JavaScript can't read it — an
  XSS payload therefore can't exfiltrate the session token.
* The **CSRF token** cookie is readable by JS and acts as the companion value
  for the double-submit-cookie pattern (the SPA echoes it back in a header).
"""
from fastapi import Response

from core.config import settings

ACCESS_COOKIE = "access_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def _cookie_security() -> dict[str, object]:
    # A SPA on a different origin (cross-site) needs SameSite=None, which
    # browsers only accept together with Secure (HTTPS). Locally we serve over
    # http, so fall back to Lax/non-secure so the cookie is still stored.
    if settings.is_production:
        return {"secure": True, "samesite": "none"}
    return {"secure": False, "samesite": "lax"}


def set_auth_cookies(response: Response, access_token: str, csrf_token: str) -> None:
    max_age = settings.JWT_EXPIRE_MINUTES * 60
    security = _cookie_security()
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=max_age,
        httponly=True,
        path="/",
        **security,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        path="/",
        **security,
    )


def set_csrf_cookie(response: Response, csrf_token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        httponly=False,
        path="/",
        **_cookie_security(),
    )


def clear_auth_cookies(response: Response) -> None:
    security = _cookie_security()
    response.delete_cookie(ACCESS_COOKIE, path="/", **security)
    response.delete_cookie(CSRF_COOKIE, path="/", **security)
