import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppNav from '../../components/AppNav/AppNav';
import { fetchAllDoctorVisits } from '../../lib/api.js';
import { getInitials } from '../../lib/buildPatient.js';
import './SessionsPage.css';

const USE_API = Boolean(import.meta.env.VITE_API_URL);

const DEMO_SESSIONS = [
  {
    id: 'visit-6',
    initials: 'JP',
    name: 'Joon Park',
    condition: 'CHF · CKD III',
    dateTime: '2h ago',
    status: 'Draft',
  },
  {
    id: 'visit-6',
    initials: 'LW',
    name: 'Lin Wei',
    condition: 'Asthma — moderate persistent',
    dateTime: '5h ago',
    status: 'Signed',
  },
  {
    id: 'visit-6',
    initials: 'AB',
    name: 'Amara Bello',
    condition: 'Type II Diabetes · HTN',
    dateTime: 'Yesterday',
    status: 'Signed',
  },
];

function formatTimeAgo(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'Just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Yesterday';
  return `${days}d ago`;
}

export default function SessionsPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState(USE_API ? [] : DEMO_SESSIONS);
  const [loading, setLoading] = useState(USE_API);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    if (!USE_API) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const visits = await fetchAllDoctorVisits();
        if (cancelled) return;
        setSessions(
          visits.map((v) => ({
            id: v.id,
            initials: getInitials(v.patient_name),
            name: v.patient_name,
            condition: v.is_signed ? 'Signed note' : 'Draft',
            dateTime: formatTimeAgo(v.visit_date),
            status: v.is_signed ? 'Signed' : 'Draft',
          })),
        );
      } catch (err) {
        console.error('[SessionsPage] load failed:', err);
        if (!cancelled) setLoadError('Could not load sessions from the API.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function openSession(visitId) {
    navigate(`/session/${visitId}`);
  }

  return (
    <div className="sessions-page">
      <AppNav />
      <main className="sessions-page__content">
        <h1 className="sessions-page__title">Sessions</h1>
        <p className="sessions-page__subtitle">Recent clinical sessions across your panel.</p>

        {loadError ? (
          <p className="sessions-page__error" role="alert">
            {loadError}
          </p>
        ) : null}

        {loading ? (
          <p className="sessions-page__empty">Loading sessions…</p>
        ) : sessions.length === 0 ? (
          <p className="sessions-page__empty">
            No sessions yet. Start one from a patient in the registry.
          </p>
        ) : (
          <ul className="sessions-page__list">
            {sessions.map((session) => (
              <li key={session.id}>
                <button
                  type="button"
                  className="sessions-page__row"
                  onClick={() => openSession(session.id)}
                >
                  <span className="sessions-page__avatar">{session.initials}</span>
                  <span className="sessions-page__info">
                    <span className="sessions-page__name">{session.name}</span>
                    <span className="sessions-page__condition">{session.condition}</span>
                  </span>
                  <span className="sessions-page__datetime">{session.dateTime}</span>
                  <span
                    className={`sessions-page__status sessions-page__status--${session.status.toLowerCase()}`}
                  >
                    {session.status}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
