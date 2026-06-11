import SidePanel from '../SidePanel/SidePanel';
import './DifferentialPanel.css';

export default function DifferentialPanel({ differentials }) {
  if (!differentials?.length) {
    return null;
  }

  return (
    <SidePanel title="Differential diagnoses" count={differentials.length}>
      <ol className="differential-panel__list">
        {differentials.map((item, index) => (
          <li key={item.diagnosis} className="differential-panel__item">
            <div className="differential-panel__rank">{index + 1}</div>
            <div className="differential-panel__body">
              <div className="differential-panel__row">
                <span className="differential-panel__name">{item.diagnosis}</span>
                <span className="differential-panel__pct">
                  {Math.round(item.confidence * 100)}%
                </span>
              </div>
              <div className="differential-panel__bar">
                <span
                  className="differential-panel__fill"
                  style={{ width: `${item.confidence * 100}%` }}
                />
              </div>
              <p className="differential-panel__fields">
                Fields: {item.contributing_fields?.join(', ')}
              </p>
            </div>
          </li>
        ))}
      </ol>
      <p className="differential-panel__disclaimer">AI suggestions — not clinical decisions</p>
    </SidePanel>
  );
}
