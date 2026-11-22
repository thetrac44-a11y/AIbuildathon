import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AppShell } from './components/layout/AppShell';
import { RouteGuard } from './components/layout/RouteGuard';
import { LoadingSkeleton } from './components/ui/LoadingSkeleton';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { AttendancePage } from './pages/AttendancePage';
import { LeavesPage } from './pages/LeavesPage';
import { AnomaliesPage } from './pages/AnomaliesPage';
import { AssistantPage } from './pages/AssistantPage';
import { ReportsPage } from './pages/ReportsPage';
import { ProfilePage } from './pages/ProfilePage';
import { ImportPage } from './pages/ImportPage';
import { EmployeesPage } from './pages/EmployeesPage';
import { AccountsPage } from './pages/AccountsPage';

export const AppRoutes: React.FC = () => {
  const { user, isLoadingAuth } = useAuth();

  if (isLoadingAuth) {
    return (
      <div className="min-h-screen bg-brand-bg flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <LoadingSkeleton rows={4} />
        </div>
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route
          path="/dashboard"
          element={
            <RouteGuard screenId="dashboard">
              <DashboardPage />
            </RouteGuard>
          }
        />
        <Route
          path="/attendance"
          element={
            <RouteGuard screenId="attendance">
              <AttendancePage />
            </RouteGuard>
          }
        />
        <Route
          path="/leaves"
          element={
            <RouteGuard screenId="leaves">
              <LeavesPage />
            </RouteGuard>
          }
        />
        <Route
          path="/anomalies"
          element={
            <RouteGuard screenId="anomalies">
              <AnomaliesPage />
            </RouteGuard>
          }
        />
        <Route
          path="/anomalies/:anomalyId"
          element={
            <RouteGuard screenId="anomalies">
              <AnomaliesPage />
            </RouteGuard>
          }
        />
        <Route
          path="/assistant"
          element={
            <RouteGuard screenId="assistant">
              <AssistantPage />
            </RouteGuard>
          }
        />
        <Route
          path="/reports"
          element={
            <RouteGuard screenId="reports">
              <ReportsPage />
            </RouteGuard>
          }
        />
        <Route
          path="/profile"
          element={
            <RouteGuard screenId="profile">
              <ProfilePage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/import"
          element={
            <RouteGuard screenId="import">
              <ImportPage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/employees"
          element={
            <RouteGuard screenId="employees">
              <EmployeesPage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/accounts"
          element={
            <RouteGuard screenId="accounts">
              <AccountsPage />
            </RouteGuard>
          }
        />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </AppShell>
  );
};

export const App: React.FC = () => (
  <AuthProvider>
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  </AuthProvider>
);

export default App;
