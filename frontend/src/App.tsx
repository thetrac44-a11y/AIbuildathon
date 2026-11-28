import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getDefaultHomePath } from './config/navigation';
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
import { DepartmentAnalyticsPage } from './pages/DepartmentAnalyticsPage';
import { SystemDashboardPage } from './pages/SystemDashboardPage';
import { RbacManagementPage } from './pages/RbacManagementPage';
import { AuditLogsPage } from './pages/AuditLogsPage';
import { RagKnowledgePage } from './pages/RagKnowledgePage';
import { SystemConfigPage } from './pages/SystemConfigPage';
import { KioskDevicesPage } from './pages/KioskDevicesPage';

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

  const defaultHome = getDefaultHomePath(user);

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to={defaultHome} replace />} />
        <Route
          path="/dashboard"
          element={
            <RouteGuard screenId="dashboard">
              <DashboardPage />
            </RouteGuard>
          }
        />
        <Route
          path="/executive/departments"
          element={
            <RouteGuard screenId="department_analytics">
              <DepartmentAnalyticsPage />
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
        <Route
          path="/admin/system"
          element={
            <RouteGuard screenId="system_dashboard">
              <SystemDashboardPage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/rbac"
          element={
            <RouteGuard screenId="rbac">
              <RbacManagementPage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <RouteGuard screenId="audit">
              <AuditLogsPage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/rag"
          element={
            <RouteGuard screenId="rag">
              <RagKnowledgePage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/config"
          element={
            <RouteGuard screenId="system_config">
              <SystemConfigPage />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/kiosk"
          element={
            <RouteGuard screenId="kiosk_devices">
              <KioskDevicesPage initialTab="devices" />
            </RouteGuard>
          }
        />
        <Route
          path="/admin/kiosk/config"
          element={
            <RouteGuard screenId="kiosk_config">
              <KioskDevicesPage initialTab="config" />
            </RouteGuard>
          }
        />
        <Route path="*" element={<Navigate to={defaultHome} replace />} />
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
