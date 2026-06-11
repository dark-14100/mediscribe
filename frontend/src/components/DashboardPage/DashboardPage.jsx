import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AppNav from '../AppNav/AppNav';
import { useAuth } from '../../lib/authContext.js';
import {
  enrichPatientRows,
  fetchAllDoctorVisits,
  fetchPatients,
  formatApiLoadError,
  mapPatientsToRows,
  openLatestVisitOrStart,
  startSessionForPatient,
} from '../../lib/api.js';
import { getInitials } from '../../lib/buildPatient.js';
import { REGISTRY_PATIENTS } from '../../lib/registryPatients.js';
import './DashboardPage.css';

const USE_API = Boolean(import.meta.env.VITE_API_URL);

const TRAJECTORY_LABELS = {
  improving: '↑ Improving',
  declining: '↓ Declining',
  stable: '→ Stable',
};

function parseAge(ageGender) {
  const match = ageGender.match(/^(\d+)/);
  return match ? match[1] : ageGender;
}

function riskBadgeLabel(risk) {
  if (risk === 'high') return 'High';
  if (risk === 'moderate') return 'Moderate';
  return risk;
}

function formatTimeAgo(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'Just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Yesterday';
  return `${days}d ago`;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const [opening, setOpening] = useState(false);
  const [patients, setPatients] = useState(USE_API ? [] : REGISTRY_PATIENTS);
  const [recentVisits, setRecentVisits] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(USE_API);

  useEffect(() => {
    if (!USE_API) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadError('');
      try {
        const raw = await fetchPatients();
        if (cancelled) return;
        setPatients(mapPatientsToRows(raw));
        setLoading(false);

        enrichPatientRows(raw)
          .then((enriched) => {
            if (!cancelled) setPatients(enriched);
          })
          .catch((err) => console.warn('[DashboardPage] enrich failed:', err));

        fetchAllDoctorVisits()
          .then((visits) => {
            if (!cancelled) setRecentVisits(visits.slice(0, 5));
          })
          .catch((err) => console.warn('[DashboardPage] visits load failed:', err));
      } catch (err) {
        console.error('[DashboardPage] load failed:', err);
        if (!cancelled) {
          if (err?.status === 401) {
            signOut();
            navigate('/login', { replace: true });
            return;
          }
          setLoadError(
            await formatApiLoadError(err, 'Could not load patients. Try signing in again.'),
          );
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const highRiskCount = patients.filter((p) => p.risk === 'high').length;
  const stats = USE_API
    ? [
        { label: 'Total patients', value: String(patients.length) },
        { label: 'High-risk', value: String(highRiskCount), accent: 'danger' },
        { label: 'Recent sessions', value: String(recentVisits.length), accent: 'primary' },
      ]
    : [
        { label: 'Total patients', value: '248' },
        { label: 'High-risk', value: '14', accent: 'danger' },
        { label: 'Live sessions', value: '3', accent: 'primary' },
      ];

  const activePatients = USE_API
    ? patients.slice(0, 3)
    : REGISTRY_PATIENTS.filter((p) => p.risk === 'high').slice(0, 3);

  async function openSessionForPatientId(patientId, mode = 'open') {
    if (opening) return;
    setOpening(true);
    setLoadError('');
    try {
      const visitId =
        mode === 'new'
          ? await startSessionForPatient(patientId)
          : await openLatestVisitOrStart(patientId);
      navigate(`/session/${visitId}`);
    } catch (err) {
      console.error('[DashboardPage] failed to open session:', err);
      setLoadError('Could not open a session for this patient.');
    } finally {
      setOpening(false);
    }
  }

  function openExistingVisit(visitId) {
    navigate(`/session/${visitId}`);
  }

  return (
    <div className="dashboard-page">
      <AppNav />
      <main className="dashboard-page__content">
        <h1 className="dashboard-page__title">Dashboard</h1>
        <p className="dashboard-page__subtitle">
          Overview of your practice and active clinical intelligence pipeline.
        </p>

        {loadError ? (
          <p className="dashboard-page__error" role="alert">
            {loadError}
          </p>
        ) : null}

        <div className="dashboard-page__stats">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className={`dashboard-page__stat ${stat.accent ? `dashboard-page__stat--${stat.accent}` : ''}`}
            >
              <span className="dashboard-page__stat-value">{stat.value}</span>
              <span className="dashboard-page__stat-label">{stat.label}</span>
            </div>
          ))}
        </div>

        <section className="dashboard-page__quick">
          <h2>Quick actions</h2>
          <div className="dashboard-page__links">
            <Link to="/patients" className="dashboard-page__link">
              View patient registry →
            </Link>
            <Link to="/sessions" className="dashboard-page__link">
              Browse sessions →
            </Link>
          </div>
        </section>

        <section className="dashboard-page__section">
          <h2 className="dashboard-page__section-title">Active patients</h2>
          {loading ? (
            <p className="dashboard-page__empty">Loading patients…</p>
          ) : activePatients.length === 0 && !loadError ? (
            <p className="dashboard-page__empty">No patients yet. Add one from the registry.</p>
          ) : activePatients.length === 0 ? null : (
            <div className="dashboard-page__active-row">
              {activePatients.map((patient) => (
                <article key={patient.id} className="dashboard-page__active-card">
                  <div className="dashboard-page__active-header">
                    <span className="dashboard-page__avatar">{patient.initials}</span>
                    <div>
                      <h3 className="dashboard-page__active-name">{patient.name}</h3>
                      <p className="dashboard-page__active-meta">
                        {parseAge(patient.ageGender)} · {patient.condition}
                      </p>
                    </div>
                  </div>
                  <div className="dashboard-page__active-badges">
                    <span
                      className={`dashboard-page__risk dashboard-page__risk--${patient.risk}`}
                    >
                      {riskBadgeLabel(patient.risk)}
                    </span>
                    <span
                      className={`dashboard-page__trajectory dashboard-page__trajectory--${patient.trajectory}`}
                    >
                      {TRAJECTORY_LABELS[patient.trajectory] ?? patient.trajectory}
                    </span>
                  </div>
                  <div className="dashboard-page__active-actions">
                    <button
                      type="button"
                      className="dashboard-page__view-link"
                      disabled={opening}
                      onClick={() => openSessionForPatientId(patient.id, 'open')}
                    >
                      {opening ? 'Opening…' : 'Open chart →'}
                    </button>
                    <button
                      type="button"
                      className="dashboard-page__new-link"
                      disabled={opening}
                      onClick={() => openSessionForPatientId(patient.id, 'new')}
                    >
                      New session
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="dashboard-page__section">
          <h2 className="dashboard-page__section-title">Recent sessions</h2>
          {USE_API && recentVisits.length === 0 ? (
            <p className="dashboard-page__empty">No sessions yet.</p>
          ) : (
            <ul className="dashboard-page__sessions-list">
              {(USE_API
                ? recentVisits.map((visit) => ({
                    key: visit.id,
                    initials: getInitials(visit.patient_name),
                    name: visit.patient_name,
                    condition: visit.is_signed ? 'Signed' : 'In progress',
                    timeAgo: formatTimeAgo(visit.visit_date),
                    status: visit.is_signed ? 'Signed' : 'Draft',
                    visitId: visit.id,
                  }))
                : [
                    {
                      key: 'jp',
                      initials: 'JP',
                      name: 'Joon Park',
                      condition: 'CHF · CKD III',
                      timeAgo: '2h ago',
                      status: 'Draft',
                      visitId: 'visit-6',
                    },
                    {
                      key: 'lw',
                      initials: 'LW',
                      name: 'Lin Wei',
                      condition: 'Asthma — moderate persistent',
                      timeAgo: '5h ago',
                      status: 'Signed',
                      visitId: 'visit-6',
                    },
                    {
                      key: 'ab',
                      initials: 'AB',
                      name: 'Amara Bello',
                      condition: 'Type II Diabetes · HTN',
                      timeAgo: 'Yesterday',
                      status: 'Signed',
                      visitId: 'visit-6',
                    },
                  ]
              ).map((session) => (
                <li key={session.key}>
                  <button
                    type="button"
                    className="dashboard-page__session-row"
                    onClick={() => openExistingVisit(session.visitId)}
                  >
                    <span className="dashboard-page__avatar">{session.initials}</span>
                    <span className="dashboard-page__session-info">
                      <span className="dashboard-page__session-name">{session.name}</span>
                      <span className="dashboard-page__session-condition">
                        {session.condition}
                      </span>
                    </span>
                    <span className="dashboard-page__session-time">{session.timeAgo}</span>
                    <span
                      className={`dashboard-page__session-status dashboard-page__session-status--${session.status.toLowerCase()}`}
                    >
                      {session.status}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  );
}
