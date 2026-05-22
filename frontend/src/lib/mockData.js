/** Handover / seed demo data — mirrors seed_demo_data.py and README § Demo identity */

export const MOCK_DOCTOR_NAME = 'Dr. Sasha Demo';

export const MOCK_COGNITIVE_LOAD = {
  session_count: 6,
  threshold: 6,
  threshold_exceeded: true,
};

export const MOCK_TRAJECTORY = {
  direction: 'down',
  score: -7,
  confidence: 82,
  computed_from_visits: 6,
  watch_zones: [
    'Anomaly count increasing 3 visits in a row (1→2→3)',
    'Drift flagged in 2 of last 3 visits',
    'Visit frequency increasing (latest gap 10d vs avg 23.3d)',
    'Chief complaint recurring: chest',
    'Chief complaint recurring: pain',
  ],
};

export const MOCK_PATIENT_SUMMARY = {
  id: '00000000-0000-4000-8000-000000000001',
  full_name: 'Maria Hernandez',
  dob: '1967-04-15',
  gender: 'female',
  allergies: ['penicillin'],
  active_medications: [
    'metformin 500 mg twice daily',
    'lisinopril 10 mg daily',
    'atorvastatin 20 mg nightly',
  ],
  last_visit_dates: [
    '2026-04-20T14:00:00Z',
    '2026-04-10T10:30:00Z',
    '2026-03-22T09:00:00Z',
  ],
  trajectory_direction: 'down',
  trajectory_confidence: 82,
  visit_count: 6,
  latest_visit_id: '00000000-0000-4000-8000-000000000006',
  latest_visit_signed: false,
  condition_summary: 'HTN + T2DM',
};

export const MOCK_DASHBOARD = {
  doctorName: MOCK_DOCTOR_NAME,
  cognitiveLoad: MOCK_COGNITIVE_LOAD,
  trajectory: MOCK_TRAJECTORY,
  patients: [MOCK_PATIENT_SUMMARY],
};
