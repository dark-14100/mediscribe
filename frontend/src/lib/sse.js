import { BASE_URL } from './api.js';

const SSE_EVENTS = [
  'soap_ready',
  'grounding_ready',
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
 * EventSource cannot set custom headers, so it authenticates via the HttpOnly
 * session cookie. `withCredentials: true` makes the browser send that cookie
 * cross-origin; the backend reads it in get_current_user_sse. (We no longer
 * pass the JWT in the URL, which would leak it via logs/history/Referer.)
 */
export function connectSSE(visitId, handlers) {
  const url = `${BASE_URL}/pipeline/stream/${visitId}`;
  const source = new EventSource(url, { withCredentials: true });

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
