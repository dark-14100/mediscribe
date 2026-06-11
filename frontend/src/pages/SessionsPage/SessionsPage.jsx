import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppNav from '../../components/AppNav/AppNav';
import { fetchAllDoctorVisits } from '../../lib/api.js';
import { getInitials } from '../../lib/buildPatient.js';
import './SessionsPage.css';

const USE_API = Boolean(import.meta.env.VITE_API_URL);

const DEMO_SESSIONS = [
  {
    key: 'demo-1',
    id: 'visit-6',
    initials: 'JP',
    name: 'Joon Park',
    condition: 'CHF · CKD III',
    visitDate: new Date(Date.now() - 2 * 3600000).toISOString(),
    status: 'Draft',
  },
  {
    key: 'demo-2',
    id: 'visit-6',
    initials: 'LW',
    name: 'Lin Wei',
    condition: 'Asthma — moderate persistent',
    visitDate: new Date(Date.now() - 5 * 3600000).toISOString(),
    status: 'Signed',
  },
  {
    key: 'demo-3',
    id: 'visit-6',
    initials: 'AB',
    name: 'Amara Bello',
    condition: 'Type II Diabetes · HTN',
    visitDate: new Date(Date.now() - 28 * 3600000).toISOString(),
    status: 'Signed',
  },
];

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'draft', label: 'Draft' },
  { value: 'signed', label: 'Signed' },
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

function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** Bucket a session into Today / Yesterday / Earlier. */
function bucketFor(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'Earlier';
  const now = new Date();
  if (isSameDay(date, now)) return 'Today';
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(date, yesterday)) return 'Yesterday';
  return 'Earlier';
}

const BUCKET_ORDER = ['Today', 'Yesterday', 'Earlier'];

export default function SessionsPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState(USE_API ? [] : DEMO_SESSIONS);
  const [loading, setLoading] = useState(USE_API);
  const [loadError, setLoadError] = useState('');
  const [filter, setFilter] = useState('all');

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
            key: v.id,
            id: v.id,
            initials: getInitials(v.patient_name),
            name: v.patient_name,
            condition: v.is_signed ? 'Signed note' : 'Draft',
            visitDate: v.visit_date,
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

  const counts = useMemo(() => {
    const draft = sessions.filter((s) => s.status === 'Draft').length;
    return { all: sessions.length, draft, signed: sessions.length - draft };
  }, [sessions]);

  const grouped = useMemo(() => {
    const filtered =
      filter === 'all'
        ? sessions
        : sessions.filter((s) => s.status.toLowerCase() === filter);
    const buckets = new Map();
    for (const session of filtered) {
      const bucket = bucketFor(session.visitDate);
      if (!buckets.has(bucket)) buckets.set(bucket, []);
      buckets.get(bucket).push(session);
    }
    return BUCKET_ORDER.filter((b) => buckets.has(b)).map((b) => ({
      bucket: b,
      items: buckets.get(b),
    }));
  }, [sessions, filter]);

  function openSession(visitId) {
    navigate(`/session/${visitId}`);
  }

  const isEmpty = grouped.length === 0;

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

        {!loading && sessions.length > 0 ? (
          <div className="sessions-page__filters" role="tablist" aria-label="Filter sessions">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                role="tab"
                aria-selected={filter === f.value}
                className={`sessions-page__filter ${
                  filter === f.value ? 'sessions-page__filter--active' : ''
                }`}
                onClick={() => setFilter(f.value)}
              >
                {f.label}
                <span className="sessions-page__filter-count">{counts[f.value]}</span>
              </button>
            ))}
          </div>
        ) : null}

        {loading ? (
          <p className="sessions-page__empty">Loading sessions…</p>
        ) : sessions.length === 0 ? (
          <p className="sessions-page__empty">
            No sessions yet. Start one from a patient in the registry.
          </p>
        ) : isEmpty ? (
          <p className="sessions-page__empty">No {filter} sessions.</p>
        ) : (
          grouped.map(({ bucket, items }) => (
            <section key={bucket} className="sessions-page__group">
              <h2 className="sessions-page__group-title">{bucket}</h2>
              <ul className="sessions-page__list">
                {items.map((session) => (
                  <li key={session.key}>
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
                      <span className="sessions-page__datetime">
                        {formatTimeAgo(session.visitDate)}
                      </span>
                      <span
                        className={`sessions-page__status sessions-page__status--${session.status.toLowerCase()}`}
                      >
                        {session.status}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </main>
    </div>
  );
}
