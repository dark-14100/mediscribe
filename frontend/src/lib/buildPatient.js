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

/** Map GET /patients row to registry table shape. */
export function mapApiPatientToRow(patient) {
  const meds = patient.active_medications || [];
  const condition =
    meds[0] || (patient.allergies?.length ? `Allergies: ${patient.allergies.join(', ')}` : '—');

  return {
    id: patient.id,
    name: patient.full_name,
    initials: getInitials(patient.full_name),
    ageGender: getAgeGender(patient.dob, patient.gender),
    mrn: `MRN-${String(patient.id).slice(0, 8)}`,
    condition,
    trajectory: 'stable',
    risk: 'low',
    visits: 0,
    lastSeen: '—',
  };
}
