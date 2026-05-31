import { clearToken, getToken } from './auth.js';

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

export async function apiFetch(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const headers = { ...options.headers };

  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(url, { ...options, headers });

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
  const res = await apiFetch('/patients');
  return res.json();
}

export async function fetchVisit(visitId) {
  const res = await apiFetch(`/visits/${visitId}`);
  return res.json();
}

export async function fetchPatientSummary(patientId) {
  const res = await apiFetch(`/patients/${patientId}/summary`);
  return res.json();
}

export async function fetchPatientVisits(patientId) {
  const res = await apiFetch(`/visits/patient/${patientId}`);
  return res.json();
}

/** All visits for the current doctor (via each patient). */
export async function fetchAllDoctorVisits() {
  const patients = await fetchPatients();
  const lists = await Promise.all(
    patients.map((p) =>
      fetchPatientVisits(p.id).then((visits) =>
        visits.map((v) => ({
          ...v,
          patient_name: p.full_name,
          patient_gender: p.gender,
        })),
      ),
    ),
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
