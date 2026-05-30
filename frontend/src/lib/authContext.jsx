import { useCallback, useEffect, useState } from 'react';
import { fetchCurrentUser } from './api.js';
import { clearToken, decodeToken, getToken, isAuthenticated } from './auth.js';
import { AuthContext } from './authContext.js';

/**
 * Resolve the best-known user info from whatever is available right now.
 *
 * Order of preference:
 *   1. /auth/me response (if reachable).
 *   2. JWT payload (gives us role + id; falls back to placeholder name).
 *   3. null (no token).
 */
async function resolveUser() {
  if (!isAuthenticated()) return null;

  const fetched = await fetchCurrentUser();
  if (fetched) return fetched;

  const payload = decodeToken(getToken());
  if (!payload) return null;
  return {
    id: payload.sub,
    role: payload.role,
    full_name: 'Demo User',
    email: 'dr.demo@example.com',
  };
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

  const signOut = useCallback(() => {
    clearToken();
    setUser(null);
    setAuthed(false);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, authed, refresh, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}
