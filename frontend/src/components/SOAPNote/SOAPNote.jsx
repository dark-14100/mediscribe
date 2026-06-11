import { useEffect, useRef } from 'react';
import './SOAPNote.css';

const FIELDS = [
  { key: 'subjective', label: 'Subjective' },
  { key: 'objective', label: 'Objective' },
  { key: 'assessment', label: 'Assessment' },
  { key: 'plan', label: 'Plan' },
];

function wordCount(text) {
  const trimmed = (text || '').trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).length;
}

function AutoGrowTextarea({ value, onChange, disabled, placeholder }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={ref}
      rows={3}
      value={value || ''}
      onChange={onChange ? (e) => onChange(e.target.value) : undefined}
      placeholder={placeholder}
      disabled={disabled}
    />
  );
}

export default function SOAPNote({ soap, visibleFields, modifiedFields, onChange }) {
  return (
    <section className="soap-note">
      <h2 className="soap-note__title">SOAP Note</h2>
      <div className="soap-note__fields">
        {FIELDS.map(({ key, label }) => {
          const visible = visibleFields?.has(key) ?? false;
          const edited = modifiedFields?.has(key) ?? false;
          const count = wordCount(soap[key]);
          return (
            <label
              key={key}
              className={`soap-note__field ${visible ? 'soap-note__field--visible' : ''}`}
            >
              <span className="soap-note__field-head">
                <span className="soap-note__label">{label}</span>
                <span className="soap-note__meta">
                  {edited ? <span className="soap-note__edited">Edited</span> : null}
                  {visible ? (
                    <span className="soap-note__words">
                      {count} {count === 1 ? 'word' : 'words'}
                    </span>
                  ) : null}
                </span>
              </span>
              <AutoGrowTextarea
                value={soap[key]}
                onChange={onChange ? (val) => onChange(key, val) : undefined}
                placeholder={visible ? '' : 'Streaming from pipeline…'}
                disabled={!visible || !onChange}
              />
            </label>
          );
        })}
      </div>
    </section>
  );
}
