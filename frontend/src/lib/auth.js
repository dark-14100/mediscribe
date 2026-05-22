const TOKEN_KEY = 'medscribe_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Decode the payload of a JWT without verifying its signature.
 * Verification is the server's job — the frontend uses this only for
 * UI hints (display name, role, expiry check).
 */
export function decodeToken(token) {
  if (!token) return null;
  try {
    const payload = token.split('.')[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '==='.slice((base64.length + 3) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

/** Returns true only if a token exists and (if present) its exp is in the future. */
export function isAuthenticated() {
  const token = getToken();
  if (!token) return false;
  const payload = decodeToken(token);
  if (payload?.exp && payload.exp * 1000 < Date.now()) {
    return false;
  }
  return true;
}
