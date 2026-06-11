import './Skeleton.css';

/** Shimmering placeholder block used while data loads. */
export default function Skeleton({ width, height = '1rem', radius = 'var(--radius-sm)', className = '', style }) {
  return (
    <span
      className={`skeleton ${className}`}
      style={{ width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
    />
  );
}

/** A row of skeleton matching the list/table rows used across pages. */
export function SkeletonRow() {
  return (
    <div className="skeleton-row">
      <Skeleton width="2.25rem" height="2.25rem" radius="var(--radius-full)" />
      <div className="skeleton-row__lines">
        <Skeleton width="40%" height="0.75rem" />
        <Skeleton width="60%" height="0.6875rem" />
      </div>
      <Skeleton width="3rem" height="0.75rem" />
    </div>
  );
}

/** A card skeleton matching the dashboard active-patient cards. */
export function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-row">
        <Skeleton width="2.25rem" height="2.25rem" radius="var(--radius-full)" />
        <div className="skeleton-row__lines">
          <Skeleton width="60%" height="0.875rem" />
          <Skeleton width="80%" height="0.6875rem" />
        </div>
      </div>
      <Skeleton width="100%" height="0.75rem" />
      <Skeleton width="40%" height="0.875rem" />
    </div>
  );
}
