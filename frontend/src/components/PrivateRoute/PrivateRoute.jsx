import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../lib/authContext.js';

/**
 * Gate component for authenticated routes.
 *
 * - While the auth context is bootstrapping (initial /auth/me call) we render
 *   nothing to avoid a flash of the protected layout.
 * - When unauthenticated we redirect to /login and remember where the user
 *   was trying to go so we can return them after a successful sign-in.
 */
export default function PrivateRoute({ children }) {
  const { authed, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return null;
  }

  if (!authed) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return children;
}
