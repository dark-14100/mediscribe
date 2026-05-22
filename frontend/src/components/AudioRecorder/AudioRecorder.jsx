import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../../lib/api.js';
import './AudioRecorder.css';

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

const STATUS_LABEL = {
  idle: 'Tap to record visit audio',
  recording: 'Recording…',
  transcribing: 'Transcribing audio…',
  error: 'Error — tap to retry',
};

/**
 * AudioRecorder
 *
 * Props:
 *   visitId            – UUID of the current visit (required for real API calls)
 *   onTranscriptReady  – called with the transcript array once transcription succeeds
 *   disabled           – blocks starting a new recording (e.g. while pipeline runs)
 */
export default function AudioRecorder({ visitId, onTranscriptReady, disabled = false }) {
  const [status, setStatus] = useState('idle');
  const [elapsed, setElapsed] = useState(0);

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const intervalRef = useRef(null);
  const streamRef = useRef(null);

  const isRecording = status === 'recording';
  const isBusy = status === 'transcribing';

  useEffect(() => {
    if (isRecording) {
      intervalRef.current = setInterval(() => setElapsed((t) => t + 1), 1000);
    } else {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    return () => clearInterval(intervalRef.current);
  }, [isRecording]);

  // Cleanup mic stream on unmount
  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function startRecording() {
    if (disabled || isBusy) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        handleTranscribe(chunksRef.current, mimeType);
      };

      recorder.start(250); // collect chunks every 250 ms
      setElapsed(0);
      setStatus('recording');
    } catch (err) {
      console.error('[AudioRecorder] getUserMedia failed:', err);
      setStatus('error');
    }
  }

  function stopRecording() {
    if (!isRecording) return;
    mediaRecorderRef.current?.stop();
    setStatus('transcribing');
  }

  async function handleTranscribe(chunks, mimeType) {
    const blob = new Blob(chunks, { type: mimeType });
    const apiBase = import.meta.env.VITE_API_URL;

    // Demo / no backend: return a placeholder so the page still works
    if (!apiBase || !visitId || visitId.startsWith('visit-')) {
      setStatus('idle');
      onTranscriptReady?.([]);
      return;
    }

    try {
      const form = new FormData();
      form.append('audio', blob, 'recording.webm');

      const url = `/pipeline/transcribe?visit_id=${encodeURIComponent(visitId)}`;
      const response = await apiFetch(url, { method: 'POST', body: form });
      const data = await response.json();

      setStatus('idle');
      onTranscriptReady?.(data.transcript ?? []);
    } catch (err) {
      console.error('[AudioRecorder] transcription failed:', err);
      setStatus('error');
    }
  }

  function handleClick() {
    if (disabled) return;
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  }

  const micClass = [
    'audio-recorder__mic',
    isRecording ? 'audio-recorder__mic--active' : '',
    isBusy ? 'audio-recorder__mic--busy' : '',
    disabled ? 'audio-recorder__mic--disabled' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <section className="audio-recorder">
      <div className="audio-recorder__inner">
        <button
          type="button"
          className={micClass}
          onClick={handleClick}
          disabled={disabled || isBusy}
          aria-label={isRecording ? 'Stop recording' : 'Start recording'}
        >
          {isBusy ? (
            <span className="audio-recorder__spinner" aria-hidden="true" />
          ) : (
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" />
              <path
                d="M6 11a6 6 0 0012 0M12 17v4M8 21h8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          )}
        </button>

        <div className="audio-recorder__meta">
          <span className="audio-recorder__label">{STATUS_LABEL[status]}</span>
          <span className="audio-recorder__timer">{isRecording ? formatTime(elapsed) : ''}</span>
        </div>

        {isRecording ? <span className="audio-recorder__pulse" aria-hidden="true" /> : null}
      </div>
    </section>
  );
}
