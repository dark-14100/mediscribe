import AppNav from '../../components/AppNav/AppNav';
import './SessionsPage.css';

export default function SessionsPage() {
  return (
    <div className="sessions-page">
      <AppNav />
      <main className="sessions-page__content">
        <h1 className="sessions-page__title">Sessions</h1>
        <p className="sessions-page__placeholder">Sessions coming soon</p>
      </main>
    </div>
  );
}
