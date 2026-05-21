import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { REGISTRY_PATIENTS } from '../../lib/registryPatients.js';
import './PatientRegistry.css';

export default function PatientRegistry({ filterSearch, onFilterSearchChange }) {
  const navigate = useNavigate();

  const filteredPatients = useMemo(() => {
    const query = filterSearch.trim().toLowerCase();
    if (!query) {
      return REGISTRY_PATIENTS;
    }
    return REGISTRY_PATIENTS.filter(
      (p) =>
        p.name.toLowerCase().includes(query) ||
        p.mrn.toLowerCase().includes(query) ||
        p.condition.toLowerCase().includes(query),
    );
  }, [filterSearch]);

  const hasQuery = filterSearch.trim().length > 0;
  const isEmpty = filteredPatients.length === 0;

  function handleRowClick(visitId) {
    navigate(`/session/${visitId}`);
  }

  return (
    <>
      <p className="registry-page__breadcrumb">248 PATIENTS · 14 HIGH-RISK</p>
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
          Filters · 3
        </button>
        <button type="button" className="registry-page__add-btn">
          + Add patient
        </button>
      </div>

      <div className="registry-table-wrap">
        {isEmpty && hasQuery ? (
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
