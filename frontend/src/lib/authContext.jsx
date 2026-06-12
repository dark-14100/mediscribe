import { useCallback, useEffect, useState } from 'react';
import { fetchCurrentUser, loadCsrfToken, logout as apiLogout } from './api.js';
import { AuthContext } from './authContext.js';

/**
 * Resolve the current user from the session cookie via /auth/me. The JWT is
 * HttpOnly so JS can't read it — the server is the single source of truth for
 * whether we're authenticated.
 */
async function resolveUser() {
  const fetched = await fetchCurrentUser();
  if (fetched) {
    // Prime the in-memory CSRF token so the first mutation doesn't have to
    // round-trip for it.
    await loadCsrfToken();
  }
  return fetched || null;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [authed, setAuthed] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const resolved = await resolveUser();
    setUser(resolved);
    setAuthed(Boolean(resolved));
    setLoading(false);
    return resolved;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const resolved = await resolveUser();
      if (cancelled) return;
      setUser(resolved);
      setAuthed(Boolean(resolved));
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(async () => {
    await apiLogout();
    setUser(null);
    setAuthed(false);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, authed, refresh, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}
