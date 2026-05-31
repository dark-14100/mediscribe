export function getInitials(fullName) {
  return fullName
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}

export function getAgeGender(dob, gender) {
  const birth = new Date(dob);
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const monthDelta = today.getMonth() - birth.getMonth();
  if (monthDelta < 0 || (monthDelta === 0 && today.getDate() < birth.getDate())) {
    age -= 1;
  }
  const suffix =
    gender === 'female' ? 'F' : gender === 'male' ? 'M' : gender.charAt(0).toUpperCase();
  return `${age}${suffix}`;
}

/** API trajectory uses up/down/stable; UI uses improving/declining/stable. */
export function mapTrajectoryDirection(apiDirection) {
  if (apiDirection === 'up') return 'improving';
  if (apiDirection === 'down') return 'declining';
  return 'stable';
}

export function deriveRisk(trajectory, visitCount) {
  if (trajectory === 'declining' && visitCount >= 4) return 'high';
  if (trajectory === 'declining') return 'moderate';
  return 'low';
}

export function formatLastSeenFromDates(dates) {
  if (!dates?.length) return '—';
  const latest = new Date(dates[0]);
  if (Number.isNaN(latest.getTime())) return '—';

  const diff = Date.now() - latest.getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'Just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Yesterday';
  return `${days}d ago`;
}

export function buildPatientFromForm(form) {
  return {
    id: crypto.randomUUID(),
    name: form.fullName.trim(),
    initials: getInitials(form.fullName),
    ageGender: getAgeGender(form.dob, form.gender),
    mrn: form.mrn.trim(),
    condition: form.condition.trim(),
    trajectory: 'stable',
    risk: 'low',
    visits: 0,
    lastSeen: 'Just now',
  };
}

/** Map GET /patients row (+ optional summary) to registry table shape. */
export function mapApiPatientToRow(patient, summary = null) {
  const meds = patient.active_medications || [];
  const condition =
    meds[0] || (patient.allergies?.length ? `Allergies: ${patient.allergies.join(', ')}` : '—');

  const trajectory = summary
    ? mapTrajectoryDirection(summary.trajectory_direction)
    : 'stable';
  const visits = summary?.last_visit_dates?.length ?? 0;
  const risk = deriveRisk(trajectory, visits);
  const lastSeen = summary ? formatLastSeenFromDates(summary.last_visit_dates) : '—';

  return {
    id: patient.id,
    name: patient.full_name,
    initials: getInitials(patient.full_name),
    ageGender: getAgeGender(patient.dob, patient.gender),
    mrn: `MRN-${String(patient.id).slice(0, 8)}`,
    condition,
    trajectory,
    risk,
    visits,
    lastSeen,
  };
}

/** Highest risk first, then name. */
export function sortPatientsForDisplay(patients) {
  const riskOrder = { high: 0, moderate: 1, low: 2 };
  return [...patients].sort((a, b) => {
    const riskDiff = (riskOrder[a.risk] ?? 3) - (riskOrder[b.risk] ?? 3);
    if (riskDiff !== 0) return riskDiff;
    return a.name.localeCompare(b.name);
  });
}
