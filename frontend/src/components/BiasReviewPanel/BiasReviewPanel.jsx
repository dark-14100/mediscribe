import './BiasReviewPanel.css';

export default function BiasReviewPanel({ flags, dismissed, onAccept, onDismiss }) {
  const visible = flags?.filter((f) => !dismissed.has(f.id)) ?? [];

  if (!flags?.length) {
    return (
      <section className="bias-review-panel">
        <h3 className="bias-review-panel__title">Bias review</h3>
        <p className="bias-review-panel__empty">Waiting for pipeline…</p>
      </section>
    );
  }

  if (!visible.length) {
    return (
      <section className="bias-review-panel">
        <h3 className="bias-review-panel__title">Bias review</h3>
        <p className="bias-review-panel__empty">No open bias flags</p>
      </section>
    );
  }

  return (
    <section className="bias-review-panel">
      <h3 className="bias-review-panel__title">Bias review</h3>
      <ul className="bias-review-panel__list">
        {visible.map((flag) => (
          <li key={flag.id} className="bias-review-panel__item">
            <span className="bias-review-panel__type">{flag.type.replace(/_/g, ' ')}</span>
            <p className="bias-review-panel__phrase">&ldquo;{flag.phrase}&rdquo;</p>
            <p className="bias-review-panel__rewrite">
              Suggested: {flag.suggested_rewrite}
            </p>
            <div className="bias-review-panel__actions">
              <button type="button" onClick={() => onAccept(flag.id)}>
                Accept
              </button>
              <button type="button" className="bias-review-panel__dismiss" onClick={() => onDismiss(flag.id)}>
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
