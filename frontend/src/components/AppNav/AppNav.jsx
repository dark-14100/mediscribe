import './AppNav.css';

export default function AppNav() {
  return (
    <header className="app-nav">
      <div className="app-nav__profile">
        <span className="app-nav__avatar" aria-hidden="true">
          DR
        </span>
        <span className="app-nav__profile-text">Dr. Okafor · On shift · 4h 12m</span>
      </div>
    </header>
  );
}
