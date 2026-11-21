import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { DevAuthProvider } from './context/DevAuthContext';
import { AppShell } from './components/layout/AppShell';
import { RouteGuard } from './components/layout/RouteGuard';
import {
  AccountsPlaceholder,
  AnomaliesPlaceholder,
  AssistantPlaceholder,
  AttendancePlaceholder,
  DashboardPlaceholder,
  EmployeesPlaceholder,
  ImportPlaceholder,
  LeavesPlaceholder,
  ProfilePlaceholder,
  ReportsPlaceholder,
} from './pages/ScreenPlaceholders';

export const AppRoutes: React.FC = () => (
  <AppShell>
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route
        path="/dashboard"
        element={
          <RouteGuard screenId="dashboard">
            <DashboardPlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/attendance"
        element={
          <RouteGuard screenId="attendance">
            <AttendancePlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/leaves"
        element={
          <RouteGuard screenId="leaves">
            <LeavesPlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/anomalies"
        element={
          <RouteGuard screenId="anomalies">
            <AnomaliesPlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/assistant"
        element={
          <RouteGuard screenId="assistant">
            <AssistantPlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/reports"
        element={
          <RouteGuard screenId="reports">
            <ReportsPlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/profile"
        element={
          <RouteGuard screenId="profile">
            <ProfilePlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/admin/import"
        element={
          <RouteGuard screenId="import">
            <ImportPlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/admin/employees"
        element={
          <RouteGuard screenId="employees">
            <EmployeesPlaceholder />
          </RouteGuard>
        }
      />
      <Route
        path="/admin/accounts"
        element={
          <RouteGuard screenId="accounts">
            <AccountsPlaceholder />
          </RouteGuard>
        }
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  </AppShell>
);

export const App: React.FC = () => (
  <DevAuthProvider>
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  </DevAuthProvider>
);

export default App;
