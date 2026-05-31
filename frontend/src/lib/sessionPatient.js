/** Map API patient summary + visit into shapes used by PatientCard / TrajectoryCard. */

/** Fallback when GET /summary fails but GET /patients/:id succeeds. */
export function mapPatientReadToSummary(patient) {
  return {
    id: patient.id,
    full_name: patient.full_name,
    dob: patient.dob,
    gender: patient.gender,
    last_visit_dates: [],
    allergies: patient.allergies || [],
    active_medications: patient.active_medications || [],
    trajectory_direction: null,
    trajectory_confidence: null,
  };
}

export function mapSummaryToPatientCard(summary, visit = null) {
  const meds = summary.active_medications || [];
  const visitCount = Math.max(summary.last_visit_dates?.length ?? 0, visit ? 1 : 0);

  return {
    full_name: summary.full_name,
    dob: summary.dob,
    gender: summary.gender,
    allergies: summary.allergies || [],
    active_medications: meds,
    last_visit_dates: summary.last_visit_dates || [],
    trajectory_direction: visit?.trajectory_direction ?? summary.trajectory_direction,
    visit_count: visitCount,
    condition_summary: meds[0] || (summary.allergies?.length ? `Allergies: ${summary.allergies.join(', ')}` : '—'),
    latest_visit_signed: visit?.is_signed ?? false,
  };
}

export function mapVisitToTrajectory(visit, summary = null) {
  const direction = visit?.trajectory_direction ?? summary?.trajectory_direction;
  if (!direction) return null;

  const score = visit?.trajectory_score ?? summary?.trajectory_confidence;
  return {
    direction,
    confidence: score != null ? Math.round(score) : (summary?.trajectory_confidence ?? 0),
    watch_zones: visit?.trajectory_watch_zones || [],
    computed_from_visits: summary?.last_visit_dates?.length ?? 0,
  };
}
