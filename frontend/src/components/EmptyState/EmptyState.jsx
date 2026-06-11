import './EmptyState.css';

/**
 * Centered empty-state with an icon, message, and optional primary action.
 *
 * Props:
 *   icon        – React node (emoji / svg)
 *   title       – heading
 *   message     – supporting line
 *   actionLabel – optional button label
 *   onAction    – optional button handler
 */
export default function EmptyState({ icon, title, message, actionLabel, onAction }) {
  return (
    <div className="empty-state">
      {icon ? (
        <div className="empty-state__icon" aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <h3 className="empty-state__title">{title}</h3>
      {message ? <p className="empty-state__message">{message}</p> : null}
      {actionLabel ? (
        <button type="button" className="empty-state__action" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
