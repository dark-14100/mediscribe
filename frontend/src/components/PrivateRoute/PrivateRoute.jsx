import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../lib/authContext.js';

/**
 * Gate component for authenticated routes.
 */
export default function PrivateRoute({ children }) {
  const { authed, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="private-route-loading" role="status">
        Loading…
      </div>
    );
  }

  if (!authed) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return children;
}
