import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from './components/AppLayout/AppLayout';
import DashboardPage from './components/DashboardPage/DashboardPage';
import LoginPage from './components/LoginPage/LoginPage';
import PatientsPage from './pages/PatientsPage/PatientsPage';
import SessionPage from './pages/SessionPage/SessionPage';
import SessionsPage from './pages/SessionsPage/SessionsPage';
import PrivateRoute from './components/PrivateRoute/PrivateRoute';
import { ToastProvider } from './components/Toast/ToastProvider.jsx';
import { AuthProvider } from './lib/authContext.jsx';

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              element={
                <PrivateRoute>
                  <AppLayout />
                </PrivateRoute>
              }
            >
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/patients" element={<PatientsPage />} />
              <Route path="/sessions" element={<SessionsPage />} />
              <Route path="/session/:visitId" element={<SessionPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  );
}
