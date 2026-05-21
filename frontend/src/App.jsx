import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from './components/AppLayout/AppLayout';
import DashboardPage from './components/DashboardPage/DashboardPage';
import LoginPage from './components/LoginPage/LoginPage';
import PatientsPage from './pages/PatientsPage/PatientsPage';
import SessionPage from './pages/SessionPage/SessionPage';
import SessionsPage from './pages/SessionsPage/SessionsPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/patients" element={<PatientsPage />} />
          <Route path="/sessions" element={<SessionsPage />} />
          <Route path="/session/:visitId" element={<SessionPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
