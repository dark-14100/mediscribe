import { useAuth } from '../../lib/authContext.js';
import './AppNav.css';

function initialsFromName(name) {
  if (!name) return 'DR';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function displayName(user) {
  if (!user?.full_name) return 'Doctor';
  if (user.role === 'doctor' && !/^dr\.?\s/i.test(user.full_name)) {
    return `Dr. ${user.full_name.split(' ').pop()}`;
  }
  return user.full_name;
}

export default function AppNav() {
  const { user } = useAuth();
  const name = displayName(user);
  const initials = initialsFromName(user?.full_name);

  return (
    <header className="app-nav">
      <div className="app-nav__profile">
        <span className="app-nav__avatar" aria-hidden="true">
          {initials}
        </span>
        <span className="app-nav__profile-text">{name} · On shift</span>
      </div>
    </header>
  );
}
