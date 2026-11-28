import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getDefaultHomePath } from './config/navigation';
import { AppShell } from './components/layout/AppShell';
import { RouteGuard } from './components/layout/RouteGuard';
import { LoadingSkeleton } from './components/ui/LoadingSkeleton';
import { LoginPage } from './pages/LoginPage';

const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const AttendancePage = lazy(() => import('./pages/AttendancePage').then((m) => ({ default: m.AttendancePage })));
const LeavesPage = lazy(() => import('./pages/LeavesPage').then((m) => ({ default: m.LeavesPage })));
const AnomaliesPage = lazy(() => import('./pages/AnomaliesPage').then((m) => ({ default: m.AnomaliesPage })));
const AssistantPage = lazy(() => import('./pages/AssistantPage').then((m) => ({ default: m.AssistantPage })));
const ReportsPage = lazy(() => import('./pages/ReportsPage').then((m) => ({ default: m.ReportsPage })));
const ProfilePage = lazy(() => import('./pages/ProfilePage').then((m) => ({ default: m.ProfilePage })));
const ImportPage = lazy(() => import('./pages/ImportPage').then((m) => ({ default: m.ImportPage })));
const EmployeesPage = lazy(() => import('./pages/EmployeesPage').then((m) => ({ default: m.EmployeesPage })));
const AccountsPage = lazy(() => import('./pages/AccountsPage').then((m) => ({ default: m.AccountsPage })));
const DepartmentAnalyticsPage = lazy(() =>
  import('./pages/DepartmentAnalyticsPage').then((m) => ({ default: m.DepartmentAnalyticsPage }))
);
const SystemDashboardPage = lazy(() =>
  import('./pages/SystemDashboardPage').then((m) => ({ default: m.SystemDashboardPage }))
);
const RbacManagementPage = lazy(() =>
  import('./pages/RbacManagementPage').then((m) => ({ default: m.RbacManagementPage }))
);
const AuditLogsPage = lazy(() => import('./pages/AuditLogsPage').then((m) => ({ default: m.AuditLogsPage })));
const RagKnowledgePage = lazy(() => import('./pages/RagKnowledgePage').then((m) => ({ default: m.RagKnowledgePage })));
const SystemConfigPage = lazy(() => import('./pages/SystemConfigPage').then((m) => ({ default: m.SystemConfigPage })));
const KioskDevicesPage = lazy(() => import('./pages/KioskDevicesPage').then((m) => ({ default: m.KioskDevicesPage })));

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
      <Suspense fallback={<LoadingSkeleton rows={5} />}>
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
      </Suspense>
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
