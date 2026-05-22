import { useAuth } from '../../lib/authContext.js';
import './AppNav.css';

function initialsFromName(name) {
  if (!name) return 'DR';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function displayName(user) {
  if (!user?.full_name) return 'Dr. Okafor';
  if (user.role === 'doctor' && !/^dr\.?\s/i.test(user.full_name)) {
    return `Dr. ${user.full_name.split(' ').pop()}`;
  }
  return user.full_name;
}

function BellIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M10 2a5 5 0 00-5 5v2.5l-1.5 2.5h13L15 9.5V7a5 5 0 00-5-5z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M8 15a2 2 0 004 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function BrightnessIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="10" r="3.5" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M10 2v2M10 16v2M2 10h2M16 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M4.2 15.8l1.4-1.4M14.4 5.6l1.4-1.4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function AppNav() {
  const { user } = useAuth();
  const name = displayName(user);
  const initials = initialsFromName(user?.full_name);

  return (
    <header className="app-nav">
      <p className="app-nav__status">
        <span className="app-nav__status-icon" aria-hidden="true">
          ⚡
        </span>
        Pipeline 142ms · Sessions 3 live
      </p>

      <div className="app-nav__actions">
        <button type="button" className="app-nav__icon-btn" aria-label="Notifications">
          <BellIcon />
          <span className="app-nav__badge">4</span>
        </button>
        <button type="button" className="app-nav__icon-btn" aria-label="Brightness">
          <BrightnessIcon />
        </button>
        <div className="app-nav__profile">
          <span className="app-nav__avatar" aria-hidden="true">
            {initials}
          </span>
          <span className="app-nav__profile-text">{name} · On shift · 4h 12m</span>
        </div>
      </div>
    </header>
  );
}
