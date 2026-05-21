import { useState } from 'react';
import AppNav from '../../components/AppNav/AppNav';
import PatientRegistry from '../../components/PatientRegistry/PatientRegistry';
import './PatientsPage.css';

export default function PatientsPage() {
  const [filterSearch, setFilterSearch] = useState('');

  return (
    <div className="patients-page">
      <AppNav />
      <main className="patients-page__content">
        <PatientRegistry
          filterSearch={filterSearch}
          onFilterSearchChange={setFilterSearch}
        />
      </main>
    </div>
  );
}
