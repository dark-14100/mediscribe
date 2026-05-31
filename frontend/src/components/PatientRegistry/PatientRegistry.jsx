import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { startSessionForPatient } from '../../lib/api.js';
import { countActiveFilters, DEFAULT_FILTERS, filterPatients } from '../../lib/filterPatients.js';
import './PatientRegistry.css';

export default function PatientRegistry({
  patients,
  loading = false,
  filterSearch,
  onFilterSearchChange,
  onOpenAddModal,
}) {
  const navigate = useNavigate();
  const [openingId, setOpeningId] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);

  const filteredPatients = useMemo(
    () => filterPatients(patients, filterSearch, filters),
    [patients, filterSearch, filters],
  );

  const activeFilterCount = countActiveFilters(filters);
  const hasQuery = filterSearch.trim().length > 0;
  const isEmpty = filteredPatients.length === 0;
  const highRisk = patients.filter((p) => p.risk === 'high').length;

  async function handleRowClick(patientId) {
    if (openingId) return;
    setOpeningId(patientId);
    try {
      const visitId = await startSessionForPatient(patientId);
      navigate(`/session/${visitId}`);
    } catch (err) {
      console.error('[PatientRegistry] failed to open session:', err);
      navigate(`/session/${patientId}`);
    } finally {
      setOpeningId(null);
    }
  }

  return (
    <>
      <p className="registry-page__breadcrumb">
        {patients.length} PATIENTS · {highRisk} HIGH-RISK
      </p>
      <h1 className="registry-page__title">Patient registry</h1>

      <div className="registry-page__toolbar">
        <input
          type="search"
          className="registry-page__filter-input"
          placeholder="Search patients..."
          value={filterSearch}
          onChange={(e) => onFilterSearchChange(e.target.value)}
          aria-label="Filter patients"
        />
        <button type="button" className="registry-page__filters-btn">
          Filters · {activeFilterCount}
        </button>
        <button type="button" className="registry-page__add-btn" onClick={onOpenAddModal}>
          + Add patient
        </button>
      </div>

      <div className="registry-table-wrap">
        {loading ? (
          <p className="registry-table__empty">Loading patients…</p>
        ) : isEmpty && !hasQuery ? (
          <p className="registry-table__empty">
            No patients yet. Add one to run an end-to-end session.
          </p>
        ) : isEmpty && hasQuery ? (
          <p className="registry-table__empty">No patients found</p>
        ) : (
          <table className="registry-table">
            <thead>
              <tr>
                <th>PATIENT</th>
                <th>MRN</th>
                <th>CONDITION</th>
                <th>TRAJECTORY</th>
                <th>RISK</th>
                <th>VISITS</th>
                <th>LAST SEEN</th>
              </tr>
            </thead>
            <tbody>
              {filteredPatients.map((patient) => (
                <tr
                  key={patient.id}
                  className="registry-table__row"
                  onClick={() => handleRowClick(patient.id)}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleRowClick(patient.id);
                    }
                  }}
                >
                  <td>
                    <div className="registry-table__patient">
                      <span className="registry-table__avatar">{patient.initials}</span>
                      <span>
                        <span className="registry-table__name">{patient.name}</span>
                        <span className="registry-table__age">{patient.ageGender}</span>
                      </span>
                    </div>
                  </td>
                  <td className="registry-table__mrn">{patient.mrn}</td>
                  <td className="registry-table__condition">{patient.condition}</td>
                  <td>
                    <span
                      className={`registry-table__trajectory registry-table__trajectory--${patient.trajectory}`}
                    >
                      <span className="registry-table__dot" aria-hidden="true">
                        ●
                      </span>
                      {patient.trajectory}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`registry-table__risk registry-table__risk--${patient.risk}`}
                    >
                      {patient.risk}
                    </span>
                  </td>
                  <td className="registry-table__visits">{patient.visits}</td>
                  <td className="registry-table__last-seen">{patient.lastSeen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
