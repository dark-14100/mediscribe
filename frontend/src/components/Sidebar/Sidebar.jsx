import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { clearToken } from '../../lib/auth.js';
import './Sidebar.css';

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/patients', label: 'Patients' },
  { to: '/sessions', label: 'Sessions' },
];

export default function Sidebar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  function isActive(path) {
    if (path === '/sessions') {
      return pathname === '/sessions' || pathname.startsWith('/session/');
    }
    return pathname === path || pathname.startsWith(`${path}/`);
  }

  function handleLogout() {
    clearToken();
    navigate('/login');
  }

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
            DR
          </span>
          <span className="sidebar__user-name">Dr. Okafor</span>
        </div>
        <button type="button" className="sidebar__logout" onClick={handleLogout}>
          Log out
        </button>
      </div>
    </aside>
  );
}
