import { clearToken, getToken } from './auth.js';
import { mapApiPatientToRow, sortPatientsForDisplay } from './buildPatient.js';

function normalizeBaseUrl(raw) {
  const base = (raw || 'http://localhost:8000').trim();
  return base.replace(/\/+$/, '');
}

export const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_URL);
export const DEMO_REGISTRY_PREFIX = '00000000-0000-4000-8000-';

export function isDemoRegistryId(patientId) {
  return !patientId || patientId.startsWith(DEMO_REGISTRY_PREFIX);
}

export function isDemoVisitId(visitId) {
  return !visitId || visitId.startsWith('visit-') || visitId.startsWith(DEMO_REGISTRY_PREFIX);
}

/** Read FastAPI ``detail`` (string or validation array) from a failed response. */
export async function readApiError(response) {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) {
      return detail.map((d) => d.msg).join('; ');
    }
  } catch {
    // ignore
  }
  return response.statusText || 'Request failed';
}

function normalizeApiPath(path) {
  if (!path.startsWith('/')) return `/${path}`;
  // Avoid /patients/ etc. — trailing slashes can hit the wrong FastAPI route.
  if (path.length > 1 && path.endsWith('/')) {
    return path.replace(/\/+$/, '');
  }
  return path;
}

export async function apiFetch(path, options = {}, { retries = 0 } = {}) {
  const url = `${BASE_URL}${normalizeApiPath(path)}`;
  const headers = { ...options.headers };

  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const method = (options.method || 'GET').toUpperCase();
  const canRetry = method === 'GET' && retries > 0;

  let response;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    response = await fetch(url, { ...options, headers });
    if (!canRetry || response.status !== 500 || attempt >= retries) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
  }

  if (response.status === 401) {
    // Token is missing, expired, or invalid — drop it so the next
    // PrivateRoute check bounces the user to /login.
    clearToken();
    const error = new Error('Unauthorized');
    error.status = 401;
    error.response = response;
    throw error;
  }

  if (!response.ok) {
    const error = new Error(`API error: ${response.status} ${response.statusText}`);
    error.status = response.status;
    error.response = response;
    throw error;
  }

  return response;
}

/**
 * Sign in without the global 401 handler (wrong password is expected here).
 * @throws {Error} with `code` of 'network' | 'credentials' | 'server'
 */
export async function login(email, password) {
  const url = `${BASE_URL}/auth/login`;
  const normalizedEmail = email.trim().toLowerCase();
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: normalizedEmail, password }),
    });
  } catch {
    const error = new Error('Cannot reach API');
    error.code = 'network';
    throw error;
  }

  if (response.status === 401) {
    const error = new Error('Invalid credentials');
    error.code = 'credentials';
    throw error;
  }

  if (response.status === 404) {
    const error = new Error('API route not found');
    error.code = 'notfound';
    error.status = 404;
    throw error;
  }

  if (!response.ok) {
    const error = new Error(`API error: ${response.status}`);
    error.code = 'server';
    error.status = response.status;
    throw error;
  }

  return response.json();
}

/** Fetch the currently authenticated user, or null if not logged in. */
export async function fetchCurrentUser() {
  const token = getToken();
  if (!token) return null;
  const url = `${BASE_URL}/auth/me`;
  try {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/** List patients for the logged-in doctor (empty array if none). */
export async function fetchPatients() {
  const res = await apiFetch('/patients', {}, { retries: 2 });
  return res.json();
}

/** Map API patient rows without summary (fast path for first paint). */
export function mapPatientsToRows(patients) {
  return sortPatientsForDisplay(patients.map((p) => mapApiPatientToRow(p)));
}

/** Add trajectory / visit metadata; never throws — falls back per patient. */
export async function enrichPatientRows(patients) {
  const rows = await Promise.all(
    patients.map(async (patient) => {
      try {
        const summary = await fetchPatientSummary(patient.id);
        return mapApiPatientToRow(patient, summary);
      } catch (err) {
        console.warn('[api] summary failed for patient', patient.id, err);
        return mapApiPatientToRow(patient);
      }
    }),
  );
  return sortPatientsForDisplay(rows);
}

/** Patients plus per-patient summary (trajectory, visit count, last seen). */
export async function fetchPatientsEnriched() {
  const patients = await fetchPatients();
  return enrichPatientRows(patients);
}

/** User-facing message for a failed patient/dashboard load. */
export async function formatApiLoadError(err, fallback) {
  if (err?.status === 401) return 'Session expired. Sign in again.';
  if (err?.response) {
    try {
      return await readApiError(err.response);
    } catch {
      // keep fallback
    }
  }
  if (err?.message?.includes('Failed to fetch') || err?.code === 'network') {
    return 'Cannot reach the API. Check your connection and try again.';
  }
  return fallback;
}

export async function fetchVisit(visitId) {
  const res = await apiFetch(`/visits/${visitId}`, {}, { retries: 2 });
  return res.json();
}

export async function fetchPatient(patientId) {
  const res = await apiFetch(`/patients/${patientId}`);
  return res.json();
}

export async function fetchPatientSummary(patientId) {
  const res = await apiFetch(`/patients/${patientId}/summary`, {}, { retries: 2 });
  return res.json();
}

export async function fetchPatientVisits(patientId) {
  try {
    const res = await apiFetch(`/visits/patient/${patientId}`, {}, { retries: 2 });
    return res.json();
  } catch (err) {
    if (err.status === 500) {
      console.warn('[api] visit list failed for patient', patientId, err);
      return [];
    }
    throw err;
  }
}

/** All visits for the current doctor (via each patient). */
export async function fetchAllDoctorVisits() {
  const patients = await fetchPatients();
  const lists = await Promise.all(
    patients.map(async (p) => {
      try {
        const visits = await fetchPatientVisits(p.id);
        return visits.map((v) => ({
          ...v,
          patient_name: p.full_name,
          patient_gender: p.gender,
        }));
      } catch (err) {
        console.warn('[api] visits for patient failed', p.id, err);
        return [];
      }
    }),
  );
  return lists
    .flat()
    .sort((a, b) => new Date(b.visit_date) - new Date(a.visit_date));
}

/**
 * Start a new session for a patient and return the resulting visit id.
 *
 * - When connected to a real backend (VITE_API_URL set and the id looks like
 *   a real UUID, not one of the demo registry ids), POSTs to /visits.
 * - In demo mode, returns the input id so the SessionPage can fall back to
 *   its mock SSE simulation.
 */

/** Create a patient on the backend; returns PatientRead JSON. */
export async function createPatient(payload) {
  const res = await apiFetch('/patients', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
}

/** Always create a NEW visit for the patient; returns the new visit id. */
export async function startSessionForPatient(patientId) {
  const apiBase = import.meta.env.VITE_API_URL;
  const isDemoId = isDemoRegistryId(patientId);

  if (!apiBase || isDemoId) {
    return patientId;
  }

  const res = await apiFetch('/visits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patient_id: patientId }),
  });
  const visit = await res.json();
  return visit.id;
}

/**
 * Open the patient's most recent visit, or start a new one if they have none.
 * Returns the visit id to navigate to.
 */
export async function openLatestVisitOrStart(patientId) {
  const apiBase = import.meta.env.VITE_API_URL;
  const isDemoId = isDemoRegistryId(patientId);

  if (!apiBase || isDemoId) {
    return patientId;
  }

  const visits = await fetchPatientVisits(patientId); // newest first, [] on failure
  if (visits.length > 0) {
    return visits[0].id;
  }
  return startSessionForPatient(patientId);
}
