import { useState } from 'react';
import './DifferentialPanel.css';

export default function DifferentialPanel({ differentials }) {
  const [open, setOpen] = useState(true);

  if (!differentials?.length) {
    return null;
  }

  return (
    <section className="differential-panel">
      <button
        type="button"
        className="differential-panel__header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>Differential diagnoses</span>
        <span className="differential-panel__count">{differentials.length}</span>
        <span className="differential-panel__chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open ? (
        <ol className="differential-panel__list">
          {differentials.map((item, index) => (
            <li key={item.diagnosis} className="differential-panel__item">
              <div className="differential-panel__rank">{index + 1}</div>
              <div className="differential-panel__body">
                <div className="differential-panel__row">
                  <span className="differential-panel__name">{item.diagnosis}</span>
                  <span className="differential-panel__pct">
                    {Math.round(item.confidence * 100)}%
                  </span>
                </div>
                <div className="differential-panel__bar">
                  <span
                    className="differential-panel__fill"
                    style={{ width: `${item.confidence * 100}%` }}
                  />
                </div>
                <p className="differential-panel__fields">
                  Fields: {item.contributing_fields?.join(', ')}
                </p>
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="differential-panel__disclaimer">AI suggestions — not clinical decisions</p>
    </section>
  );
}
