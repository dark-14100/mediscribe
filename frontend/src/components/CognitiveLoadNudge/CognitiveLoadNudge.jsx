import './CognitiveLoadNudge.css';

export default function CognitiveLoadNudge({ sessionCount, onDismiss }) {
  return (
    <div className="cognitive-load-nudge" role="status">
      <p>
        You&apos;ve completed {sessionCount}+ sessions today — review this note
        carefully before signing.
      </p>
      <button type="button" className="cognitive-load-nudge__dismiss" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}
