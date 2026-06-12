"""CSRF protection middleware (double-submit cookie).

Cookie auth sends the session token *ambiently* on every request, which is what
makes cross-site request forgery possible. We defend with the double-submit
pattern: the readable ``csrf_token`` cookie must be echoed back in the
``X-CSRF-Token`` header on every state-changing request, and the two must match.

The check only applies when the request authenticates via the cookie. Callers
using ``Authorization: Bearer`` (API clients, the test suite) are not subject to
CSRF — a forged request can't attach an Authorization header — so they skip it.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.cookies import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Auth endpoints establish/tear down the session and run before a CSRF token
# exists, so they are exempt; healthz is unauthenticated.
_EXEMPT_PATHS = frozenset({"/auth/login", "/auth/register", "/auth/logout", "/healthz"})


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if (
            request.method not in _SAFE_METHODS
            and request.url.path not in _EXEMPT_PATHS
        ):
            authorization = request.headers.get("authorization", "")
            has_bearer = authorization.lower().startswith("bearer ")
            access_cookie = request.cookies.get(ACCESS_COOKIE)
            if access_cookie and not has_bearer:
                cookie_token = request.cookies.get(CSRF_COOKIE)
                header_token = request.headers.get(CSRF_HEADER)
                if not cookie_token or header_token != cookie_token:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF token missing or invalid"},
                    )
        return await call_next(request)
