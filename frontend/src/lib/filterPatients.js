export const DEFAULT_FILTERS = {
  risk: 'all',
  trajectory: 'all',
  lastSeen: 'any',
};

export function countActiveFilters(filters) {
  let count = 0;
  if (filters.risk !== 'all') count += 1;
  if (filters.trajectory !== 'all') count += 1;
  if (filters.lastSeen !== 'any') count += 1;
  return count;
}

function matchesLastSeen(lastSeen, lastSeenFilter) {
  if (lastSeenFilter === 'any') return true;

  const value = lastSeen.toLowerCase();
  const isToday =
    value.includes('h ago') || value.includes('just now') || value === 'today';

  const isThisWeek =
    isToday ||
    value === 'yesterday' ||
    /\d+d ago/.test(value) ||
    value === '1w ago';

  if (lastSeenFilter === 'today') return isToday;
  if (lastSeenFilter === 'week') return isThisWeek;
  return true;
}

export function filterPatients(patients, searchQuery, filters) {
  const query = searchQuery.trim().toLowerCase();

  return patients.filter((patient) => {
    if (query) {
      const matchesSearch =
        patient.name.toLowerCase().includes(query) ||
        patient.mrn.toLowerCase().includes(query) ||
        patient.condition.toLowerCase().includes(query);
      if (!matchesSearch) return false;
    }

    if (filters.risk !== 'all' && patient.risk !== filters.risk) {
      return false;
    }

    if (filters.trajectory !== 'all' && patient.trajectory !== filters.trajectory) {
      return false;
    }

    if (!matchesLastSeen(patient.lastSeen, filters.lastSeen)) {
      return false;
    }

    return true;
  });
}
