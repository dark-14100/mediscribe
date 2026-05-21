import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../../lib/api.js';
import { setToken } from '../../lib/auth.js';
import './LoginPage.css';

const DEMO_EMAIL = 'dr.demo@medscribe.test';
const DEMO_PASSWORD = 'demo1234';

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
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [loginFailed, setLoginFailed] = useState(false);
  const [loading, setLoading] = useState(false);

  function clearLoginError() {
    setLoginFailed(false);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setLoginFailed(false);
    setLoading(true);

    try {
      const response = await apiFetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await response.json();
      setToken(data.access_token);
      navigate('/dashboard');
    } catch {
      setLoginFailed(true);
    } finally {
      setLoading(false);
    }
  }

  function handleSkipDemo() {
    navigate('/dashboard');
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
            {loginFailed ? (
              <p className="login-page__error" role="alert">
                Invalid credentials. Use the demo account or check your API connection.
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

          <p className="login-page__demo-hint">
            Demo: <code>{DEMO_EMAIL}</code> / <code>{DEMO_PASSWORD}</code>
          </p>

          <button
            type="button"
            className="login-page__skip"
            onClick={handleSkipDemo}
          >
            Skip to dashboard →
          </button>
        </div>
      </section>
    </div>
  );
}
