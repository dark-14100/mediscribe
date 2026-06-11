import './ConfirmDialog.css';

/**
 * Generic confirmation modal for destructive / irreversible actions.
 *
 * Props:
 *   open, title, message
 *   confirmLabel, cancelLabel
 *   tone        – 'primary' | 'danger' (confirm button style)
 *   busy        – disables buttons while the action runs
 *   onConfirm, onCancel
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'primary',
  busy = false,
  onConfirm,
  onCancel,
}) {
  if (!open) return null;

  function handleBackdropClick(event) {
    if (event.target === event.currentTarget && !busy) onCancel();
  }

  return (
    <div className="confirm-dialog__backdrop" onClick={handleBackdropClick} role="presentation">
      <div
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        <h2 id="confirm-dialog-title" className="confirm-dialog__title">
          {title}
        </h2>
        {message ? <p className="confirm-dialog__message">{message}</p> : null}
        <div className="confirm-dialog__actions">
          <button
            type="button"
            className="confirm-dialog__cancel"
            onClick={onCancel}
            disabled={busy}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`confirm-dialog__confirm confirm-dialog__confirm--${tone}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
