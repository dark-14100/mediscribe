import { getToken } from './auth.js';

export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function apiFetch(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const headers = { ...options.headers };

  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    const error = new Error(`API error: ${response.status} ${response.statusText}`);
    error.status = response.status;
    error.response = response;
    throw error;
  }

  return response;
}
