import { useState } from 'react';
import './SidePanel.css';

/**
 * Collapsible section used for the session intelligence feed
 * (anomalies, differentials, bias). Gives every panel a consistent
 * header with a count badge and chevron.
 *
 * Props:
 *   title       – heading text
 *   count       – optional number rendered as a badge
 *   tone        – 'default' | 'alert' | 'danger' (count badge color)
 *   defaultOpen – initial expanded state (default true)
 *   emptyLabel  – shown when count === 0
 *   children    – panel body
 */
export default function SidePanel({
  title,
  count,
  tone = 'default',
  defaultOpen = true,
  emptyLabel = 'Nothing yet.',
  children,
}) {
  const [open, setOpen] = useState(defaultOpen);
  const hasCount = typeof count === 'number';
  const isEmpty = hasCount && count === 0;

  return (
    <section className="side-panel">
      <button
        type="button"
        className="side-panel__header"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="side-panel__title">{title}</span>
        {hasCount ? (
          <span className={`side-panel__count side-panel__count--${isEmpty ? 'default' : tone}`}>
            {count}
          </span>
        ) : null}
        <span className="side-panel__chevron" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
      </button>
      {open ? (
        <div className="side-panel__body">
          {isEmpty ? <p className="side-panel__empty">{emptyLabel}</p> : children}
        </div>
      ) : null}
    </section>
  );
}
