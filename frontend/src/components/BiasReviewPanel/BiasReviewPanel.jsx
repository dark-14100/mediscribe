import SidePanel from '../SidePanel/SidePanel';
import './BiasReviewPanel.css';

export default function BiasReviewPanel({ flags, dismissed, onAccept, onDismiss }) {
  const visible = flags?.filter((f) => !dismissed.has(f.id)) ?? [];

  // Before the pipeline returns, show a waiting hint rather than "0".
  if (!flags?.length) {
    return (
      <SidePanel title="Bias review" emptyLabel="Waiting for pipeline…">
        <p className="bias-review-panel__empty">Waiting for pipeline…</p>
      </SidePanel>
    );
  }

  return (
    <SidePanel
      title="Bias review"
      count={visible.length}
      tone="alert"
      emptyLabel="No open bias flags — all reviewed."
    >
      <ul className="bias-review-panel__list">
        {visible.map((flag) => (
          <li key={flag.id} className="bias-review-panel__item">
            <span className="bias-review-panel__type">{flag.type.replace(/_/g, ' ')}</span>
            <p className="bias-review-panel__phrase">&ldquo;{flag.phrase}&rdquo;</p>
            <p className="bias-review-panel__rewrite">Suggested: {flag.suggested_rewrite}</p>
            <div className="bias-review-panel__actions">
              <button type="button" onClick={() => onAccept(flag.id)}>
                Accept
              </button>
              <button
                type="button"
                className="bias-review-panel__dismiss"
                onClick={() => onDismiss(flag.id)}
              >
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>
    </SidePanel>
  );
}
