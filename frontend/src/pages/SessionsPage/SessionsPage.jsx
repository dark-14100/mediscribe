import { useNavigate } from 'react-router-dom';
import AppNav from '../../components/AppNav/AppNav';
import './SessionsPage.css';

const SESSIONS = [
  {
    initials: 'JP',
    name: 'Joon Park',
    condition: 'CHF · CKD III',
    dateTime: '2h ago',
    status: 'Draft',
  },
  {
    initials: 'LW',
    name: 'Lin Wei',
    condition: 'Asthma — moderate persistent',
    dateTime: '5h ago',
    status: 'Signed',
  },
  {
    initials: 'AB',
    name: 'Amara Bello',
    condition: 'Type II Diabetes · HTN',
    dateTime: 'Yesterday',
    status: 'Signed',
  },
];

export default function SessionsPage() {
  const navigate = useNavigate();

  function openSession() {
    navigate('/session/visit-6');
  }

  return (
    <div className="sessions-page">
      <AppNav />
      <main className="sessions-page__content">
        <h1 className="sessions-page__title">Sessions</h1>
        <p className="sessions-page__subtitle">Recent clinical sessions across your panel.</p>

        <ul className="sessions-page__list">
          {SESSIONS.map((session) => (
            <li key={session.name}>
              <button
                type="button"
                className="sessions-page__row"
                onClick={openSession}
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
      </main>
    </div>
  );
}
