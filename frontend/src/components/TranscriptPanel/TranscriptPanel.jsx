import { useState } from 'react';
import './TranscriptPanel.css';

const SPEAKER_LABEL = {
  doctor: 'Doctor',
  patient: 'Patient',
};

/**
 * Collapsible diarised transcript so the doctor can verify what was heard
 * before trusting the generated SOAP note.
 *
 * Props:
 *   lines – [{ speaker, text, line_index }]
 */
export default function TranscriptPanel({ lines }) {
  const [open, setOpen] = useState(false);

  if (!lines?.length) return null;

  return (
    <section className={`transcript-panel ${open ? 'transcript-panel--open' : ''}`}>
      <button
        type="button"
        className="transcript-panel__header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="transcript-panel__title">
          Transcript
          <span className="transcript-panel__count">{lines.length} lines</span>
        </span>
        <span className="transcript-panel__chevron" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
      </button>

      {open ? (
        <ol className="transcript-panel__lines">
          {lines.map((line, i) => (
            <li
              key={line.line_index ?? i}
              className={`transcript-panel__line transcript-panel__line--${line.speaker}`}
            >
              <span className="transcript-panel__speaker">
                {SPEAKER_LABEL[line.speaker] ?? line.speaker}
              </span>
              <span className="transcript-panel__text">{line.text}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
