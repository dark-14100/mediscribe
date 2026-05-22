import { getToken } from './auth.js';
import { BASE_URL } from './api.js';

const SSE_EVENTS = [
  'soap_ready',
  'anomalies_ready',
  'differentials_ready',
  'drift_ready',
  'compliance_ready',
  'bias_ready',
  'trajectory_ready',
  'pipeline_done',
  'error',
];

/**
 * Open a real SSE connection to /pipeline/stream/{visitId}.
 *
 * EventSource cannot set custom headers, so the JWT is passed as ?token=...
 * The backend accepts this via the get_current_user_sse dependency.
 */
export function connectSSE(visitId, handlers) {
  const token = getToken();
  const params = token ? `?token=${encodeURIComponent(token)}` : '';
  const url = `${BASE_URL}/pipeline/stream/${visitId}${params}`;
  const source = new EventSource(url);

  for (const eventName of SSE_EVENTS) {
    source.addEventListener(eventName, (event) => {
      if (handlers[eventName]) {
        handlers[eventName](event);
      }
    });
  }

  return {
    source,
    close() {
      source.close();
    },
  };
}
