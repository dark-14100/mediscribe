import { Link, useNavigate } from 'react-router-dom';
import AppNav from '../AppNav/AppNav';
import { REGISTRY_PATIENTS } from '../../lib/registryPatients.js';
import './DashboardPage.css';

const STATS = [
  { label: 'Total patients', value: '248' },
  { label: 'High-risk', value: '14', accent: 'danger' },
  { label: 'Live sessions', value: '3', accent: 'primary' },
  { label: 'Pipeline latency', value: '142ms', accent: 'primary' },
];

const RECENT_SESSIONS = [
  {
    initials: 'JP',
    name: 'Joon Park',
    condition: 'CHF · CKD III',
    timeAgo: '2h ago',
    status: 'Draft',
  },
  {
    initials: 'LW',
    name: 'Lin Wei',
    condition: 'Asthma — moderate persistent',
    timeAgo: '5h ago',
    status: 'Signed',
  },
  {
    initials: 'AB',
    name: 'Amara Bello',
    condition: 'Type II Diabetes · HTN',
    timeAgo: 'Yesterday',
    status: 'Signed',
  },
];

const TRAJECTORY_LABELS = {
  improving: '↑ Improving',
  declining: '↓ Declining',
  stable: '→ Stable',
};

const ACTIVE_PATIENTS = REGISTRY_PATIENTS.filter((p) => p.risk === 'high').slice(0, 3);

function parseAge(ageGender) {
  const match = ageGender.match(/^(\d+)/);
  return match ? match[1] : ageGender;
}

function riskBadgeLabel(risk) {
  if (risk === 'high') return 'High';
  if (risk === 'moderate') return 'Moderate';
  return risk;
}

export default function DashboardPage() {
  const navigate = useNavigate();

  function openSession() {
    navigate('/session/visit-6');
  }

  return (
    <div className="dashboard-page">
      <AppNav />
      <main className="dashboard-page__content">
        <h1 className="dashboard-page__title">Dashboard</h1>
        <p className="dashboard-page__subtitle">
          Overview of your practice and active clinical intelligence pipeline.
        </p>

        <div className="dashboard-page__stats">
          {STATS.map((stat) => (
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
          <div className="dashboard-page__active-row">
            {ACTIVE_PATIENTS.map((patient) => (
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
                    {TRAJECTORY_LABELS[patient.trajectory]}
                  </span>
                </div>
                <Link to="/patients" className="dashboard-page__view-link">
                  View →
                </Link>
              </article>
            ))}
          </div>
        </section>

        <section className="dashboard-page__section">
          <h2 className="dashboard-page__section-title">Recent sessions</h2>
          <ul className="dashboard-page__sessions-list">
            {RECENT_SESSIONS.map((session) => (
              <li key={session.name}>
                <button
                  type="button"
                  className="dashboard-page__session-row"
                  onClick={openSession}
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
        </section>
      </main>
    </div>
  );
}
