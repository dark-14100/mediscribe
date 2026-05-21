import './AnomalyFlag.css';

export default function AnomalyFlag({ anomaly }) {
  return (
    <article className={`anomaly-flag anomaly-flag--${anomaly.severity}`}>
      <span className="anomaly-flag__badge">{anomaly.severity}</span>
      <p className="anomaly-flag__description">{anomaly.description}</p>
      <button type="button" className="anomaly-flag__source">
        Line {anomaly.source_line}
      </button>
    </article>
  );
}
