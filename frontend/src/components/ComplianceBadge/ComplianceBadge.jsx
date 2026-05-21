import { useState } from 'react';
import './ComplianceBadge.css';

const STATUS_LABELS = {
  pass: 'Pass',
  warn: 'Warn',
  fail: 'Fail',
};

export default function ComplianceBadge({ compliance }) {
  const [expanded, setExpanded] = useState(false);

  if (!compliance?.status) {
    return null;
  }

  const status = compliance.status;

  return (
    <div className={`compliance-badge compliance-badge--${status}`}>
      <button
        type="button"
        className="compliance-badge__toggle"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span className="compliance-badge__status">Compliance: {STATUS_LABELS[status]}</span>
        <span className="compliance-badge__chevron">{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && compliance.notes?.length > 0 ? (
        <ul className="compliance-badge__notes">
          {compliance.notes.map((note) => (
            <li key={`${note.field}-${note.issue.slice(0, 24)}`}>
              <strong>{note.field}</strong>: {note.issue}
              {note.suggestion ? (
                <p className="compliance-badge__suggestion">→ {note.suggestion}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
