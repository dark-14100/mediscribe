/** Session mock — Maria Hernandez visit 6 (seed / handover demo) */

import { REGISTRY_PATIENTS } from './registryPatients.js';
import { MOCK_PATIENT_SUMMARY, MOCK_TRAJECTORY } from './mockData.js';

export const MOCK_SOAP = {
  subjective:
    'Elderly woman who is anxious presents with constant chest pain, dyspnea, and palpitations. The patient is noncompliant with her dietary recommendations. Pain is burning, throbbing, radiates to the jaw and left arm.',
  objective:
    'BP 174/104, HR 102, RR 22, SpO2 94% on room air. Cardiac exam: tachycardic, S4 gallop, no murmurs. ECG: ST depression in V4–V6. Troponin elevated at 0.18.',
  assessment:
    'Non-ST elevation myocardial infarction (NSTEMI) in the setting of poorly controlled HTN and T2DM. ICD-10: I21.4.',
  plan:
    'Transfer to ED for emergent cardiac catheterization. Continue current medications until handoff. Direct admission to cardiology service. Family notified.',
};

export const MOCK_ANOMALIES = [
  {
    id: 'a1',
    severity: 'high',
    type: 'outlier_vital',
    description:
      'SpO2 94% on room air with tachypnea — possible pulmonary edema, requires immediate evaluation.',
    source_line: 5,
  },
  {
    id: 'a2',
    severity: 'high',
    type: 'contradictory_symptom',
    description:
      'Crescendo pattern from exertional to constant chest pain over three visits — classic NSTEMI progression.',
    source_line: 8,
  },
  {
    id: 'a3',
    severity: 'medium',
    type: 'drug_interaction',
    description:
      'Patient on metformin presenting with possible cardiogenic shock — hold metformin to reduce lactic acidosis risk pending contrast study.',
    source_line: 10,
  },
];

export const MOCK_DIFFERENTIALS = [
  {
    diagnosis: 'NSTEMI',
    confidence: 0.94,
    contributing_fields: ['subjective', 'objective', 'assessment'],
  },
  {
    diagnosis: 'Acute decompensated heart failure',
    confidence: 0.66,
    contributing_fields: ['objective'],
  },
  {
    diagnosis: 'Pulmonary embolism',
    confidence: 0.31,
    contributing_fields: ['objective'],
  },
];

export const MOCK_COMPLIANCE = {
  status: 'warn',
  notes: [
    {
      field: 'plan',
      issue:
        'Plan should document time-stamped handoff to the receiving cardiology team for medico-legal continuity.',
      suggestion:
        'Add explicit time of transfer and name of receiving provider once known.',
    },
  ],
};

export const MOCK_BIAS_FLAGS = [
  {
    id: 'b1',
    phrase: 'the patient is noncompliant with her dietary recommendations',
    type: 'socioeconomic_bias',
    suggested_rewrite:
      'the patient reports challenges adhering to dietary recommendations',
  },
  {
    id: 'b2',
    phrase: 'Elderly woman who is anxious',
    type: 'age_bias',
    suggested_rewrite: '58-year-old patient who reports anxiety',
  },
];

const TRAJECTORY_MAP = {
  improving: 'up',
  declining: 'down',
  stable: 'stable',
};

function registryToPatient(registryRow) {
  const age = parseInt(registryRow.ageGender, 10);
  const genderChar = registryRow.ageGender.slice(-1);
  const gender = genderChar === 'F' ? 'female' : genderChar === 'M' ? 'male' : registryRow.ageGender;

  return {
    full_name: registryRow.name,
    dob: '1967-04-15',
    gender,
    allergies: registryRow.name === 'Maria Hernandez' ? ['penicillin'] : [],
    active_medications:
      registryRow.name === 'Maria Hernandez'
        ? MOCK_PATIENT_SUMMARY.active_medications
        : [],
    last_visit_dates: MOCK_PATIENT_SUMMARY.last_visit_dates,
    trajectory_direction: TRAJECTORY_MAP[registryRow.trajectory] || registryRow.trajectory,
    visit_count: registryRow.visits,
    condition_summary: registryRow.condition,
  };
}

export function getSessionPatient(visitId) {
  const registry = REGISTRY_PATIENTS.find((p) => p.id === visitId);
  if (registry) {
    return registryToPatient(registry);
  }
  return {
    full_name: MOCK_PATIENT_SUMMARY.full_name,
    dob: MOCK_PATIENT_SUMMARY.dob,
    gender: MOCK_PATIENT_SUMMARY.gender,
    allergies: MOCK_PATIENT_SUMMARY.allergies,
    active_medications: MOCK_PATIENT_SUMMARY.active_medications,
    last_visit_dates: MOCK_PATIENT_SUMMARY.last_visit_dates,
    trajectory_direction: MOCK_PATIENT_SUMMARY.trajectory_direction,
    visit_count: MOCK_PATIENT_SUMMARY.visit_count,
    condition_summary: MOCK_PATIENT_SUMMARY.condition_summary,
  };
}

export function getInitialTrajectory(visitId) {
  const registry = REGISTRY_PATIENTS.find((p) => p.id === visitId);
  if (registry) {
    const direction = TRAJECTORY_MAP[registry.trajectory] || 'stable';
    return {
      direction,
      confidence: direction === 'down' ? 82 : direction === 'up' ? 74 : 61,
      watch_zones: direction === 'down' ? MOCK_TRAJECTORY.watch_zones : [],
      computed_from_visits: registry.visits,
    };
  }
  return { ...MOCK_TRAJECTORY };
}

/** Staggered mock SSE for demo when backend stream is unavailable */
export function simulateSessionSSE(handlers, visitId) {
  const schedule = [
    ['soap_ready', { soap_note: MOCK_SOAP }, 400],
    ['anomalies_ready', { anomalies: MOCK_ANOMALIES }, 900],
    ['differentials_ready', { differentials: MOCK_DIFFERENTIALS }, 1400],
    ['compliance_ready', MOCK_COMPLIANCE, 1900],
    ['bias_ready', { bias_flags: MOCK_BIAS_FLAGS }, 2400],
    ['trajectory_ready', getInitialTrajectory(visitId), 2900],
  ];

  const timers = schedule.map(([name, data, delay]) =>
    setTimeout(() => {
      if (handlers[name]) {
        handlers[name]({ data: JSON.stringify(data) });
      }
    }, delay),
  );

  return {
    close() {
      timers.forEach(clearTimeout);
    },
  };
}

export function parseSSEData(event) {
  try {
    return JSON.parse(event.data);
  } catch {
    return null;
  }
}
