import './TrajectoryCard.css';

const DIRECTION_META = {
  up: { label: 'Improving', arrow: '↑', modifier: 'up' },
  stable: { label: 'Stable', arrow: '→', modifier: 'stable' },
  down: { label: 'Declining', arrow: '↓', modifier: 'down' },
};

export default function TrajectoryCard({ trajectory }) {
  if (!trajectory?.direction) {
    return null;
  }

  const meta = DIRECTION_META[trajectory.direction] || DIRECTION_META.stable;

  return (
    <section className={`trajectory-card trajectory-card--${meta.modifier}`}>
      <div className="trajectory-card__main">
        <span className="trajectory-card__arrow" aria-hidden="true">
          {meta.arrow}
        </span>
        <div>
          <h2 className="trajectory-card__title">Patient trajectory</h2>
          <p className="trajectory-card__direction">{meta.label}</p>
        </div>
        <div className="trajectory-card__confidence">
          <span className="trajectory-card__confidence-value">
            {trajectory.confidence}%
          </span>
          <span className="trajectory-card__confidence-label">confidence</span>
        </div>
      </div>

      {trajectory.watch_zones?.length > 0 ? (
        <div className="trajectory-card__zones">
          <h3>Watch zones</h3>
          <ul>
            {trajectory.watch_zones.map((zone) => (
              <li key={zone}>{zone}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
