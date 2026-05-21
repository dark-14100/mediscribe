import './SOAPNote.css';

const FIELDS = [
  { key: 'subjective', label: 'Subjective' },
  { key: 'objective', label: 'Objective' },
  { key: 'assessment', label: 'Assessment' },
  { key: 'plan', label: 'Plan' },
];

export default function SOAPNote({ soap, visibleFields, onChange }) {
  return (
    <section className="soap-note">
      <h2 className="soap-note__title">SOAP Note</h2>
      <div className="soap-note__fields">
        {FIELDS.map(({ key, label }) => {
          const visible = visibleFields?.has(key) ?? false;
          return (
            <label
              key={key}
              className={`soap-note__field ${visible ? 'soap-note__field--visible' : ''}`}
            >
              <span className="soap-note__label">{label}</span>
              <textarea
                rows={4}
                value={soap[key] || ''}
                onChange={(e) => onChange(key, e.target.value)}
                placeholder={visible ? '' : 'Streaming from pipeline…'}
                disabled={!visible}
              />
            </label>
          );
        })}
      </div>
    </section>
  );
}
