/**
 * Auth token handling.
 *
 * The session JWT lives in an HttpOnly cookie that the browser manages and
 * JavaScript can never read — this is what makes the app resistant to token
 * theft via XSS. The frontend therefore keeps NO token in localStorage.
 *
 * The only thing we hold here is the CSRF token (double-submit pattern). With a
 * cross-site API the CSRF cookie is set on the API origin and is not readable
 * via document.cookie, so we fetch it from GET /auth/csrf and keep it in memory
 * to echo back in the X-CSRF-Token header on state-changing requests.
 */
let csrfToken = null;

export function setCsrfToken(token) {
  csrfToken = token || null;
}

export function getCsrfToken() {
  return csrfToken;
}

export function clearCsrfToken() {
  csrfToken = null;
}
