import { useEffect, useRef, useState } from 'react';
import './AudioRecorder.css';

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function AudioRecorder({ onRecordingComplete }) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (recording) {
      intervalRef.current = setInterval(() => {
        setElapsed((t) => t + 1);
      }, 1000);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [recording]);

  function toggleRecording() {
    if (recording) {
      setRecording(false);
      if (onRecordingComplete) {
        onRecordingComplete();
      }
    } else {
      setElapsed(0);
      setRecording(true);
    }
  }

  return (
    <section className="audio-recorder">
      <div className="audio-recorder__inner">
        <button
          type="button"
          className={`audio-recorder__mic ${recording ? 'audio-recorder__mic--active' : ''}`}
          onClick={toggleRecording}
          aria-label={recording ? 'Stop recording' : 'Start recording'}
        >
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" />
            <path
              d="M6 11a6 6 0 0012 0M12 17v4M8 21h8"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
        <div className="audio-recorder__meta">
          <span className="audio-recorder__label">
            {recording ? 'Recording…' : 'Tap to record visit audio'}
          </span>
          <span className="audio-recorder__timer">{formatTime(elapsed)}</span>
        </div>
        {recording ? (
          <span className="audio-recorder__pulse" aria-hidden="true" />
        ) : null}
      </div>
    </section>
  );
}
