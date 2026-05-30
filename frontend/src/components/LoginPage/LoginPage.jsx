import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { login as apiLogin } from '../../lib/api.js';
import { setToken } from '../../lib/auth.js';
import { useAuth } from '../../lib/authContext.js';
import './LoginPage.css';

const LOGIN_ERRORS = {
  network:
    "Can't reach the server. Confirm the API is running and VITE_API_URL points to your Railway backend.",
  credentials: 'Email or password is incorrect.',
  server: 'Something went wrong on the server. Try again in a moment.',
};

const FEATURES = [
  { label: 'Live SOAP', icon: 'soap' },
  { label: 'Trajectory', icon: 'trajectory' },
  { label: 'Compliance', icon: 'compliance' },
];

function LogoMark() {
  return (
    <svg
      className="login-page__logo-mark"
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="40" height="40" rx="10" fill="var(--color-primary)" />
      <path
        d="M12 20h16M20 12v16"
        stroke="#fff"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="20" cy="20" r="5" fill="#fff" fillOpacity="0.35" />
    </svg>
  );
}

function FeatureIcon({ type }) {
  if (type === 'soap') {
    return (
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path
          d="M5 4h10v12H5V4z"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <path d="M7 8h6M7 11h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  if (type === 'trajectory') {
    return (
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path
          d="M4 14l4-4 3 3 5-7"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M14 6h2v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M10 3l7 3v5c0 4.2-3 7.5-7 8-4-.5-7-3.8-7-8V6l7-3z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M7 10l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refresh } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const redirectTo = location.state?.from || '/dashboard';

  function clearLoginError() {
    setErrorMessage('');
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setErrorMessage('');
    setLoading(true);

    try {
      const data = await apiLogin(email, password);
      setToken(data.access_token);
      await refresh();
      navigate(redirectTo, { replace: true });
    } catch (err) {
      const code = err?.code === 'credentials' || err?.code === 'network' || err?.code === 'server'
        ? err.code
        : 'server';
      setErrorMessage(LOGIN_ERRORS[code]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <aside className="login-page__brand">
        <div className="login-page__brand-inner">
          <div className="login-page__logo">
            <LogoMark />
            <span className="login-page__logo-text">MedScribe</span>
          </div>

          <p className="login-page__tagline">
            Documentation that remembers every visit
          </p>

          <ul className="login-page__features">
            {FEATURES.map((feature) => (
              <li key={feature.label} className="login-page__badge">
                <span className="login-page__badge-icon">
                  <FeatureIcon type={feature.icon} />
                </span>
                {feature.label}
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <section className="login-page__form-panel">
        <div className="login-page__form-wrap">
          <header className="login-page__form-header">
            <h1>Sign in</h1>
            <p>Access your patient sessions and longitudinal intelligence.</p>
          </header>

          <form className="login-page__form" onSubmit={handleSubmit}>
            {errorMessage ? (
              <p className="login-page__error" role="alert">
                {errorMessage}
              </p>
            ) : null}

            {!import.meta.env.VITE_API_URL ? (
              <p className="login-page__error" role="alert">
                API URL is not configured. Set VITE_API_URL on Vercel to your Railway backend and
                redeploy.
              </p>
            ) : null}

            <label className="login-page__field">
              <span>Email</span>
              <input
                type="email"
                name="email"
                autoComplete="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  clearLoginError();
                }}
                required
              />
            </label>

            <label className="login-page__field">
              <span>Password</span>
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  clearLoginError();
                }}
                required
              />
            </label>

            <button
              type="submit"
              className="login-page__submit"
              disabled={loading}
            >
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
