import { useCallback, useEffect, useState } from 'react';
import AddPatientModal from '../../components/AddPatientModal/AddPatientModal';
import AppNav from '../../components/AppNav/AppNav';
import PatientRegistry from '../../components/PatientRegistry/PatientRegistry';
import { createPatient, fetchPatients, readApiError } from '../../lib/api.js';
import { buildPatientFromForm, mapApiPatientToRow } from '../../lib/buildPatient.js';
import { REGISTRY_PATIENTS } from '../../lib/registryPatients.js';
import './PatientsPage.css';

const USE_API = Boolean(import.meta.env.VITE_API_URL);

export default function PatientsPage() {
  const [patients, setPatients] = useState(USE_API ? [] : REGISTRY_PATIENTS);
  const [filterSearch, setFilterSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(USE_API);
  const [loadError, setLoadError] = useState('');

  const reloadPatients = useCallback(async () => {
    if (!USE_API) return;
    setLoading(true);
    setLoadError('');
    try {
      const rows = await fetchPatients();
      const mapped = [];
      for (const row of rows) {
        try {
          mapped.push(mapApiPatientToRow(row));
        } catch (mapErr) {
          console.warn('[PatientsPage] skip invalid patient row', row?.id, mapErr);
        }
      }
      setPatients(mapped);
    } catch (err) {
      let message = 'Could not load patients from the API.';
      if (err?.response) {
        try {
          message = await readApiError(err.response);
        } catch {
          // keep default
        }
      } else if (err?.status === 401) {
        message = 'Session expired. Sign in again.';
      }
      setLoadError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reloadPatients();
  }, [reloadPatients]);

  async function handleAddPatient(form) {
    if (USE_API) {
      try {
        const created = await createPatient({
          full_name: form.fullName.trim(),
          dob: form.dob,
          gender: form.gender,
          allergies: [],
          active_medications: form.condition.trim() ? [form.condition.trim()] : [],
        });
        setPatients((prev) => [mapApiPatientToRow(created), ...prev]);
        setModalOpen(false);
      } catch {
        setLoadError('Could not create patient. Try again.');
      }
      return;
    }

    const newPatient = buildPatientFromForm(form);
    setPatients((prev) => [newPatient, ...prev]);
    setModalOpen(false);
  }

  return (
    <div className="patients-page">
      <AppNav />
      <main className="patients-page__content">
        {loadError ? (
          <p className="patients-page__error" role="alert">
            {loadError}
          </p>
        ) : null}
        <PatientRegistry
          patients={patients}
          loading={loading}
          filterSearch={filterSearch}
          onFilterSearchChange={setFilterSearch}
          onOpenAddModal={() => setModalOpen(true)}
        />
      </main>
      <AddPatientModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSubmit={handleAddPatient}
      />
    </div>
  );
}
