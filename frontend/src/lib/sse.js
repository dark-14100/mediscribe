import { BASE_URL } from './api.js';

const SSE_EVENTS = [
  'soap_ready',
  'anomalies_ready',
  'differentials_ready',
  'drift_ready',
  'compliance_ready',
  'bias_ready',
  'trajectory_ready',
];

export function connectSSE(visitId, handlers) {
  const url = `${BASE_URL}/pipeline/stream/${visitId}`;
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
