import { useState } from 'react';
import AddPatientModal from '../../components/AddPatientModal/AddPatientModal';
import AppNav from '../../components/AppNav/AppNav';
import PatientRegistry from '../../components/PatientRegistry/PatientRegistry';
import { buildPatientFromForm } from '../../lib/buildPatient.js';
import { REGISTRY_PATIENTS } from '../../lib/registryPatients.js';
import './PatientsPage.css';

export default function PatientsPage() {
  const [patients, setPatients] = useState(REGISTRY_PATIENTS);
  const [filterSearch, setFilterSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);

  function handleAddPatient(form) {
    const newPatient = buildPatientFromForm(form);
    setPatients((prev) => [newPatient, ...prev]);
    setModalOpen(false);
  }

  return (
    <div className="patients-page">
      <AppNav />
      <main className="patients-page__content">
        <PatientRegistry
          patients={patients}
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
