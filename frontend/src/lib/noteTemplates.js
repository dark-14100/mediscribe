// Mirror of backend/core/note_templates.py — the section shapes per note type.
// Keep in sync with the backend registry.

export const DEFAULT_NOTE_TYPE = 'soap';

export const NOTE_TEMPLATES = {
  soap: {
    label: 'SOAP note',
    sections: [
      { key: 'subjective', label: 'Subjective' },
      { key: 'objective', label: 'Objective' },
      { key: 'assessment', label: 'Assessment' },
      { key: 'plan', label: 'Plan' },
    ],
  },
  hp: {
    label: 'History & Physical',
    sections: [
      { key: 'chief_complaint', label: 'Chief Complaint' },
      { key: 'hpi', label: 'History of Present Illness' },
      { key: 'pmh', label: 'Past Medical History' },
      { key: 'ros', label: 'Review of Systems' },
      { key: 'exam', label: 'Physical Exam' },
      { key: 'assessment', label: 'Assessment' },
      { key: 'plan', label: 'Plan' },
    ],
  },
  progress: {
    label: 'Progress note',
    sections: [
      { key: 'interval_history', label: 'Interval History' },
      { key: 'exam', label: 'Exam / Findings' },
      { key: 'assessment', label: 'Assessment' },
      { key: 'plan', label: 'Plan' },
    ],
  },
  discharge: {
    label: 'Discharge summary',
    sections: [
      { key: 'admission_dx', label: 'Admission Diagnosis' },
      { key: 'discharge_dx', label: 'Discharge Diagnosis' },
      { key: 'hospital_course', label: 'Hospital Course' },
      { key: 'discharge_meds', label: 'Discharge Medications' },
      { key: 'followup', label: 'Follow-up Instructions' },
    ],
  },
};

export function normalizeNoteType(noteType) {
  const key = (noteType || '').toLowerCase();
  return NOTE_TEMPLATES[key] ? key : DEFAULT_NOTE_TYPE;
}

export function getTemplate(noteType) {
  return NOTE_TEMPLATES[normalizeNoteType(noteType)];
}

export function sectionKeys(noteType) {
  return getTemplate(noteType).sections.map((s) => s.key);
}

export function sectionFields(noteType) {
  return getTemplate(noteType).sections;
}

export function emptyNote(noteType) {
  const out = {};
  for (const key of sectionKeys(noteType)) out[key] = '';
  return out;
}

export function noteTypeChoices() {
  return Object.entries(NOTE_TEMPLATES).map(([key, tpl]) => ({ key, label: tpl.label }));
}
