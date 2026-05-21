import './PatientCard.css';

function formatVisitDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function ageFromDob(dob) {
  const birth = new Date(dob);
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const monthDelta = today.getMonth() - birth.getMonth();
  if (monthDelta < 0 || (monthDelta === 0 && today.getDate() < birth.getDate())) {
    age -= 1;
  }
  return age;
}

const TRAJECTORY_BADGE = {
  up: { label: '↑ Improving', className: 'up' },
  stable: { label: '→ Stable', className: 'stable' },
  down: { label: '↓ Declining', className: 'down' },
};

export default function PatientCard({ patient, onOpenSession, variant = 'default' }) {
  const isSession = variant === 'session';
  const badge = patient.trajectory_direction
    ? TRAJECTORY_BADGE[patient.trajectory_direction]
    : null;
  const age = ageFromDob(patient.dob);
  const genderLabel = patient.gender === 'female' ? 'F' : patient.gender === 'male' ? 'M' : patient.gender;
  const sessionLabel = patient.latest_visit_signed ? 'View latest visit' : 'Continue session';

  return (
    <article className={`patient-card ${isSession ? 'patient-card--session' : ''}`}>
      <div className="patient-card__header">
        <div>
          <h2 className="patient-card__name">{patient.full_name}</h2>
          <p className="patient-card__meta">
            {age}
            {genderLabel} · {patient.condition_summary || '—'} · {patient.visit_count}{' '}
            {patient.visit_count === 1 ? 'visit' : 'visits'}
          </p>
        </div>
        {badge ? (
          <span className={`patient-card__trajectory patient-card__trajectory--${badge.className}`}>
            {badge.label}
          </span>
        ) : null}
      </div>

      {patient.last_visit_dates?.length > 0 ? (
        <div className="patient-card__visits">
          <span className="patient-card__label">Recent visits</span>
          <ul>
            {patient.last_visit_dates.slice(0, 3).map((date) => (
              <li key={date}>{formatVisitDate(date)}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="patient-card__details">
        {patient.allergies?.length > 0 ? (
          <div className="patient-card__detail">
            <span className="patient-card__label">Allergies</span>
            <p>{patient.allergies.join(', ')}</p>
          </div>
        ) : null}
        {patient.active_medications?.length > 0 ? (
          <div className="patient-card__detail">
            <span className="patient-card__label">Medications</span>
            <p>{patient.active_medications.join(' · ')}</p>
          </div>
        ) : null}
      </div>

      {!isSession && onOpenSession ? (
        <button type="button" className="patient-card__action" onClick={onOpenSession}>
          {sessionLabel}
        </button>
      ) : null}
    </article>
  );
}
