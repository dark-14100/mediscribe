import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../lib/authContext.js';
import './Sidebar.css';

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/patients', label: 'Patients' },
  { to: '/sessions', label: 'Sessions' },
];

function initialsFromName(name) {
  if (!name) return 'DR';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function displayName(user) {
  if (!user?.full_name) return 'Dr. Okafor';
  // Doctors get a "Dr." prefix if they haven't already provided one
  if (user.role === 'doctor' && !/^dr\.?\s/i.test(user.full_name)) {
    return `Dr. ${user.full_name.split(' ').pop()}`;
  }
  return user.full_name;
}

export default function Sidebar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { user, signOut } = useAuth();

  function isActive(path) {
    if (path === '/sessions') {
      return pathname === '/sessions' || pathname.startsWith('/session/');
    }
    return pathname === path || pathname.startsWith(`${path}/`);
  }

  function handleLogout() {
    signOut();
    navigate('/login');
  }

  const name = displayName(user);
  const initials = initialsFromName(user?.full_name);

  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__logo-mark" aria-hidden="true" />
        <div>
          <span className="sidebar__logo-text">MedScribe</span>
          <span className="sidebar__subtitle">Clinical OS</span>
        </div>
      </div>

      <nav className="sidebar__nav" aria-label="Main">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={`sidebar__link ${isActive(item.to) ? 'sidebar__link--active' : ''}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar__footer">
        <div className="sidebar__user">
          <span className="sidebar__avatar" aria-hidden="true">
            {initials}
          </span>
          <span className="sidebar__user-name">{name}</span>
        </div>
        <button type="button" className="sidebar__logout" onClick={handleLogout}>
          Log out
        </button>
      </div>
    </aside>
  );
}
