import { useState } from 'react';
import './CodingPanel.css';

const FIELD_LABELS = {
  subjective: 'Subjective',
  objective: 'Objective',
  assessment: 'Assessment',
  plan: 'Plan',
};

function confidenceTone(confidence) {
  if (confidence >= 0.75) return 'high';
  if (confidence >= 0.5) return 'medium';
  return 'low';
}

function CodeRow({ suggestion }) {
  const tone = confidenceTone(suggestion.confidence ?? 0);
  const pct = Math.round((suggestion.confidence ?? 0) * 100);
  const field = suggestion.evidence_field ? FIELD_LABELS[suggestion.evidence_field] : null;

  return (
    <li className="coding-panel__row">
      <div className="coding-panel__row-head">
        <code className="coding-panel__code">{suggestion.code}</code>
        <span className={`coding-panel__confidence coding-panel__confidence--${tone}`}>
          {pct}%
        </span>
      </div>
      {suggestion.description ? (
        <p className="coding-panel__desc">{suggestion.description}</p>
      ) : null}
      {suggestion.rationale ? (
        <p className="coding-panel__rationale">{suggestion.rationale}</p>
      ) : null}
      {field ? (
        <span className="coding-panel__evidence">
          from {field}
          {suggestion.evidence_lines?.length
            ? ` · lines ${suggestion.evidence_lines.join(', ')}`
            : ''}
        </span>
      ) : null}
    </li>
  );
}

function CodeGroup({ title, items }) {
  if (!items?.length) return null;
  return (
    <div className="coding-panel__group">
      <h4 className="coding-panel__group-title">{title}</h4>
      <ul className="coding-panel__list">
        {items.map((s) => (
          <CodeRow key={`${s.system}-${s.code}`} suggestion={s} />
        ))}
      </ul>
    </div>
  );
}

export default function CodingPanel({ coding }) {
  const [expanded, setExpanded] = useState(false);

  const icd10 = coding?.icd10 ?? [];
  const cpt = coding?.cpt ?? [];
  const em = coding?.em ?? null;
  const total = icd10.length + cpt.length + (em ? 1 : 0);

  if (!coding || total === 0) {
    return null;
  }

  const disclaimer =
    coding.disclaimer ||
    'AI-suggested codes are advisory. The provider is responsible for final code selection before billing.';

  return (
    <div className="coding-panel">
      <button
        type="button"
        className="coding-panel__toggle"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span className="coding-panel__title">
          Suggested codes
          <span className="coding-panel__count">{total}</span>
          <span className="coding-panel__badge">Advisory</span>
        </span>
        <span className="coding-panel__chevron">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded ? (
        <div className="coding-panel__body">
          <CodeGroup title="Diagnoses (ICD-10)" items={icd10} />
          <CodeGroup title="Procedures (CPT)" items={cpt} />
          {em ? (
            <CodeGroup title={`Visit level (E&M · ${coding.patient_class})`} items={[em]} />
          ) : null}
          <p className="coding-panel__disclaimer">{disclaimer}</p>
        </div>
      ) : null}
    </div>
  );
}
