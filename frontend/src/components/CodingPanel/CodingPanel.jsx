import { useState } from 'react';
import './CodingPanel.css';

const FIELD_LABELS = {
  subjective: 'Subjective',
  objective: 'Objective',
  assessment: 'Assessment',
  plan: 'Plan',
};

const SYSTEMS = ['ICD-10', 'CPT', 'E&M'];

const keyOf = (s) => `${s.system}:${s.code}`;

function confidenceTone(confidence) {
  if (confidence >= 0.75) return 'high';
  if (confidence >= 0.5) return 'medium';
  return 'low';
}

function emptyDecisions() {
  return { accepted: [], dismissed: [] };
}

function EditForm({ initialCode, initialDescription, onSave, onCancel }) {
  const [code, setCode] = useState(initialCode);
  const [description, setDescription] = useState(initialDescription);
  const trimmed = code.trim();
  return (
    <div className="coding-panel__edit">
      <input
        className="coding-panel__input coding-panel__input--code"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="Code"
        aria-label="Code"
      />
      <input
        className="coding-panel__input"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description"
        aria-label="Description"
      />
      <div className="coding-panel__edit-actions">
        <button
          type="button"
          className="coding-panel__btn coding-panel__btn--primary"
          disabled={!trimmed}
          onClick={() => onSave(trimmed, description.trim())}
        >
          Save
        </button>
        <button type="button" className="coding-panel__btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function SuggestionRow({ suggestion, status, accepted, readOnly, editing, onEditStart, onEditCancel, onAction }) {
  const tone = confidenceTone(suggestion.confidence ?? 0);
  const pct = Math.round((suggestion.confidence ?? 0) * 100);
  const field = suggestion.evidence_field ? FIELD_LABELS[suggestion.evidence_field] : null;
  // When accepted-and-edited, show the doctor's values; otherwise the AI's.
  const shownCode = accepted ? accepted.code : suggestion.code;
  const shownDesc = accepted ? accepted.description : suggestion.description;
  const wasEdited = accepted?.origin === 'edited';

  if (editing) {
    return (
      <li className="coding-panel__row coding-panel__row--editing">
        <EditForm
          initialCode={shownCode}
          initialDescription={shownDesc || ''}
          onSave={(code, description) => onAction('edit', { code, description })}
          onCancel={onEditCancel}
        />
      </li>
    );
  }

  return (
    <li className={`coding-panel__row coding-panel__row--${status}`}>
      <div className="coding-panel__row-head">
        <code className="coding-panel__code">{shownCode}</code>
        <div className="coding-panel__row-meta">
          {wasEdited ? <span className="coding-panel__tag">edited</span> : null}
          {status === 'accepted' ? (
            <span className="coding-panel__status-pill coding-panel__status-pill--accepted">Added</span>
          ) : status === 'dismissed' ? (
            <span className="coding-panel__status-pill coding-panel__status-pill--dismissed">Dismissed</span>
          ) : (
            <span className={`coding-panel__confidence coding-panel__confidence--${tone}`}>{pct}%</span>
          )}
        </div>
      </div>
      {shownDesc ? <p className="coding-panel__desc">{shownDesc}</p> : null}
      {status === 'pending' && suggestion.rationale ? (
        <p className="coding-panel__rationale">{suggestion.rationale}</p>
      ) : null}
      {field ? (
        <span className="coding-panel__evidence">
          from {field}
          {suggestion.evidence_lines?.length ? ` · lines ${suggestion.evidence_lines.join(', ')}` : ''}
        </span>
      ) : null}

      {!readOnly ? (
        <div className="coding-panel__actions">
          {status === 'pending' ? (
            <>
              <button
                type="button"
                className="coding-panel__btn coding-panel__btn--primary"
                onClick={() => onAction('confirm')}
              >
                Confirm
              </button>
              <button type="button" className="coding-panel__btn" onClick={onEditStart}>
                Edit
              </button>
              <button
                type="button"
                className="coding-panel__btn coding-panel__btn--ghost"
                onClick={() => onAction('dismiss')}
              >
                Dismiss
              </button>
            </>
          ) : status === 'accepted' ? (
            <>
              <button type="button" className="coding-panel__btn" onClick={onEditStart}>
                Edit
              </button>
              <button
                type="button"
                className="coding-panel__btn coding-panel__btn--ghost"
                onClick={() => onAction('remove')}
              >
                Remove
              </button>
            </>
          ) : (
            <button
              type="button"
              className="coding-panel__btn"
              onClick={() => onAction('undo')}
            >
              Undo
            </button>
          )}
        </div>
      ) : null}
    </li>
  );
}

function ManualAddForm({ onAdd }) {
  const [open, setOpen] = useState(false);
  const [system, setSystem] = useState('ICD-10');
  const [code, setCode] = useState('');
  const [description, setDescription] = useState('');

  if (!open) {
    return (
      <button
        type="button"
        className="coding-panel__btn coding-panel__add-toggle"
        onClick={() => setOpen(true)}
      >
        + Add a code
      </button>
    );
  }

  const trimmed = code.trim();
  return (
    <div className="coding-panel__manual">
      <select
        className="coding-panel__input coding-panel__input--system"
        value={system}
        onChange={(e) => setSystem(e.target.value)}
        aria-label="Code system"
      >
        {SYSTEMS.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <input
        className="coding-panel__input coding-panel__input--code"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="Code"
        aria-label="Code"
      />
      <input
        className="coding-panel__input"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description"
        aria-label="Description"
      />
      <div className="coding-panel__edit-actions">
        <button
          type="button"
          className="coding-panel__btn coding-panel__btn--primary"
          disabled={!trimmed}
          onClick={() => {
            onAdd({ system, code: trimmed, description: description.trim() });
            setCode('');
            setDescription('');
            setOpen(false);
          }}
        >
          Add
        </button>
        <button
          type="button"
          className="coding-panel__btn"
          onClick={() => {
            setOpen(false);
            setCode('');
            setDescription('');
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function CodingPanel({ coding, decisions, onChange, readOnly = false }) {
  const [expanded, setExpanded] = useState(false);
  const [editingKey, setEditingKey] = useState(null);

  const icd10 = coding?.icd10 ?? [];
  const cpt = coding?.cpt ?? [];
  const em = coding?.em ?? null;
  const suggestions = [...icd10, ...cpt, ...(em ? [em] : [])];

  const decided = decisions || emptyDecisions();
  const acceptedBySource = new Map(
    decided.accepted.filter((a) => a.source_key).map((a) => [a.source_key, a]),
  );
  const dismissedSet = new Set(decided.dismissed || []);
  const manualCodes = decided.accepted.filter((a) => a.origin === 'manual');

  const total = suggestions.length + manualCodes.length;
  if (total === 0) {
    return null;
  }

  const acceptedCount =
    decided.accepted.filter((a) => !a.source_key || acceptedBySource.has(a.source_key)).length;

  const statusOf = (suggestion) => {
    const k = keyOf(suggestion);
    if (acceptedBySource.has(k)) return 'accepted';
    if (dismissedSet.has(k)) return 'dismissed';
    return 'pending';
  };

  const emit = (next) => {
    onChange?.(next);
  };

  const handleAction = (suggestion, action, payload) => {
    const k = keyOf(suggestion);
    const accepted = decided.accepted.filter((a) => a.source_key !== k);
    const dismissed = (decided.dismissed || []).filter((d) => d !== k);

    if (action === 'confirm') {
      accepted.push({
        system: suggestion.system,
        code: suggestion.code,
        description: suggestion.description || '',
        origin: 'ai',
        source_key: k,
      });
      emit({ accepted, dismissed });
    } else if (action === 'dismiss') {
      emit({ accepted, dismissed: [...dismissed, k] });
    } else if (action === 'undo') {
      emit({ accepted, dismissed });
    } else if (action === 'remove') {
      emit({ accepted, dismissed });
    } else if (action === 'edit') {
      const newCode = payload.code;
      accepted.push({
        system: suggestion.system,
        code: newCode,
        description: payload.description || '',
        origin: newCode === suggestion.code ? 'ai' : 'edited',
        source_key: k,
      });
      emit({ accepted, dismissed });
      setEditingKey(null);
    }
  };

  const handleAddManual = (entry) => {
    emit({
      accepted: [
        ...decided.accepted,
        { ...entry, origin: 'manual', source_key: null },
      ],
      dismissed: decided.dismissed || [],
    });
  };

  const handleRemoveManual = (idx) => {
    let seen = -1;
    const accepted = decided.accepted.filter((a) => {
      if (a.origin !== 'manual') return true;
      seen += 1;
      return seen !== idx;
    });
    emit({ accepted, dismissed: decided.dismissed || [] });
  };

  const groups = [
    { title: 'Diagnoses (ICD-10)', items: icd10 },
    { title: 'Procedures (CPT)', items: cpt },
    em ? { title: `Visit level (E&M · ${coding.patient_class})`, items: [em] } : null,
  ].filter(Boolean);

  const disclaimer =
    coding?.disclaimer ||
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
          {acceptedCount > 0 ? (
            <span className="coding-panel__count coding-panel__count--accepted">
              {acceptedCount} added
            </span>
          ) : null}
          <span className="coding-panel__badge">Advisory</span>
        </span>
        <span className="coding-panel__chevron">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded ? (
        <div className="coding-panel__body">
          {groups.map((group) => (
            <div className="coding-panel__group" key={group.title}>
              <h4 className="coding-panel__group-title">{group.title}</h4>
              <ul className="coding-panel__list">
                {group.items.map((s) => {
                  const k = keyOf(s);
                  return (
                    <SuggestionRow
                      key={k}
                      suggestion={s}
                      status={statusOf(s)}
                      accepted={acceptedBySource.get(k) || null}
                      readOnly={readOnly}
                      editing={editingKey === k}
                      onEditStart={() => setEditingKey(k)}
                      onEditCancel={() => setEditingKey(null)}
                      onAction={(action, payload) => handleAction(s, action, payload)}
                    />
                  );
                })}
              </ul>
            </div>
          ))}

          {manualCodes.length > 0 ? (
            <div className="coding-panel__group">
              <h4 className="coding-panel__group-title">Added by you</h4>
              <ul className="coding-panel__list">
                {manualCodes.map((m, idx) => (
                  <li className="coding-panel__row coding-panel__row--accepted" key={`${m.system}:${m.code}:${idx}`}>
                    <div className="coding-panel__row-head">
                      <code className="coding-panel__code">
                        {m.system} {m.code}
                      </code>
                      {!readOnly ? (
                        <button
                          type="button"
                          className="coding-panel__btn coding-panel__btn--ghost"
                          onClick={() => handleRemoveManual(idx)}
                        >
                          Remove
                        </button>
                      ) : null}
                    </div>
                    {m.description ? <p className="coding-panel__desc">{m.description}</p> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {!readOnly ? <ManualAddForm onAdd={handleAddManual} /> : null}

          <p className="coding-panel__disclaimer">{disclaimer}</p>
        </div>
      ) : null}
    </div>
  );
}
