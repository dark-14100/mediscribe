import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { login as apiLogin } from '../../lib/api.js';
import { useAuth } from '../../lib/authContext.js';
import './LoginPage.css';

const LOGIN_ERRORS = {
  network: "Can't reach MedScribe right now. Try again in a moment.",
  credentials: 'Email or password is incorrect.',
  notfound: 'The sign-in service is unavailable. Try again in a moment.',
  server: 'Something went wrong on the server. Try again in a moment.',
};

const DEMO_ACCOUNT = {
  email: 'dr.demo@example.com',
  password: 'demo1234',
};

const FEATURES = [
  { label: 'Live SOAP notes', detail: 'Structured as the visit unfolds', icon: 'soap' },
  { label: 'Longitudinal memory', detail: 'Change surfaced across every visit', icon: 'trajectory' },
  { label: 'Trust layer', detail: 'Grounding and compliance built in', icon: 'compliance' },
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
  const [loadingAction, setLoadingAction] = useState(null);

  const redirectTo = location.state?.from || '/dashboard';

  function clearLoginError() {
    setErrorMessage('');
  }

  async function signIn(loginEmail, loginPassword, destination, action) {
    setErrorMessage('');
    setLoadingAction(action);

    try {
      // The backend sets the HttpOnly session cookie on this response; we don't
      // store the token ourselves. refresh() then hydrates the user via /auth/me
      // and primes the CSRF token.
      await apiLogin(loginEmail, loginPassword);
      await refresh();
      navigate(destination, { replace: true });
    } catch (err) {
      const code =
        err?.code === 'credentials' ||
        err?.code === 'network' ||
        err?.code === 'notfound' ||
        err?.code === 'server'
          ? err.code
          : 'server';
      setErrorMessage(LOGIN_ERRORS[code]);
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    await signIn(email, password, redirectTo, 'signin');
  }

  async function handleDemo() {
    await signIn(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password, '/dashboard', 'demo');
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
            One visit tells a story.<br />Six visits reveal the pattern.
          </p>

          <p className="login-page__brand-copy">
            MedScribe turns the clinical conversation into a structured record,
            then keeps watching what changes over time.
          </p>

          <ul className="login-page__features">
            {FEATURES.map((feature) => (
              <li key={feature.label} className="login-page__feature">
                <span className="login-page__badge-icon">
                  <FeatureIcon type={feature.icon} />
                </span>
                <span>
                  <strong>{feature.label}</strong>
                  <small>{feature.detail}</small>
                </span>
              </li>
            ))}
          </ul>

          <svg className="login-page__trajectory" viewBox="0 0 560 170" aria-hidden="true">
            <path d="M10 125C92 124 104 69 180 82s105 74 181 40 98-94 189-102" />
            <circle cx="10" cy="125" r="5" />
            <circle cx="180" cy="82" r="5" />
            <circle cx="361" cy="122" r="5" />
            <circle cx="550" cy="20" r="5" />
          </svg>
        </div>
      </aside>

      <section className="login-page__form-panel">
        <div className="login-page__form-wrap">
          <header className="login-page__form-header">
            <h1>Enter the workspace</h1>
            <p>Review patient sessions, notes, and longitudinal signals.</p>
          </header>

          {errorMessage ? (
            <p className="login-page__error" role="alert">
              {errorMessage}
            </p>
          ) : null}

          <section className="login-page__demo" aria-labelledby="demo-title">
            <div>
              <h2 id="demo-title">Tour the seeded patient record</h2>
              <p>Maria Hernandez · 6 visits · longitudinal decline</p>
            </div>
            <button
              type="button"
              className="login-page__demo-button"
              onClick={handleDemo}
              disabled={Boolean(loadingAction)}
            >
              {loadingAction === 'demo' ? 'Opening demo…' : 'Open demo workspace'}
            </button>
            <dl className="login-page__demo-credentials">
              <div>
                <dt>Email</dt>
                <dd>{DEMO_ACCOUNT.email}</dd>
              </div>
              <div>
                <dt>Password</dt>
                <dd>{DEMO_ACCOUNT.password}</dd>
              </div>
            </dl>
          </section>

          <div className="login-page__divider"><span>or sign in</span></div>

          <form className="login-page__form" onSubmit={handleSubmit}>
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
              disabled={Boolean(loadingAction)}
            >
              {loadingAction === 'signin' ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
