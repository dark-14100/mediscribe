import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchPatientVisits } from '../../lib/api.js';
import { JUDGE_DEMO_PATIENT_NAME } from '../../lib/buildPatient.js';
import './JudgeDemoBanner.css';

/**
 * One-click entry to Maria Hernandez visit 6 (seeded judge storyline).
 */
export default function JudgeDemoBanner({ patients }) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const maria = patients?.find((p) => p.name === JUDGE_DEMO_PATIENT_NAME || p.isDemoHighlight);

  if (!maria) {
    return (
      <div className="judge-demo-banner judge-demo-banner--muted" role="note">
        <strong>Judge demo:</strong> Run{' '}
        <code>python seed/seed_demo_data.py</code> against production to load Maria Hernandez
        (6 visits, declining trajectory).
      </div>
    );
  }

  async function openLatestChart() {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      const visits = await fetchPatientVisits(maria.id);
      if (!visits.length) {
        setError('No visits found for Maria. Re-run the demo seed script.');
        return;
      }
      navigate(`/session/${visits[0].id}`);
    } catch (err) {
      console.error('[JudgeDemoBanner]', err);
      setError('Could not open Maria’s chart. Try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="judge-demo-banner">
      <div className="judge-demo-banner__text">
        <strong>Judge demo — {JUDGE_DEMO_PATIENT_NAME}</strong>
        <span>
          6-visit storyline: drift, anomalies, compliance gaps, bias flags, downward trajectory.
        </span>
      </div>
      <button type="button" className="judge-demo-banner__btn" onClick={openLatestChart} disabled={loading}>
        {loading ? 'Opening…' : 'Open latest chart (visit 6)'}
      </button>
      {error ? (
        <p className="judge-demo-banner__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
