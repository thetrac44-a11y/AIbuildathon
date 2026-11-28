import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, AuthUser } from '../context/AuthContext';
import { PermissionGuard } from '../components/layout/PermissionGuard';
import {
  DEFAULT_ROLE_PERMISSIONS,
  getDataScopeLabel,
  getDefaultHomePath,
  resolvePermissions,
} from '../config/navigation';
import { AppRoutes } from '../App';
import { UserRole } from '../types/navigation';

function makeUser(role: UserRole, permissions?: string[]): AuthUser {
  return {
    user_id: `USR-${role.toUpperCase()}`,
    username: `${role}@company.vn`,
    employee_id: role === 'hr' ? 'NV002' : role === 'manager' ? 'NV001' : role === 'executive' ? 'NV079' : role === 'admin' ? 'NV080' : 'NV007',
    full_name: `Test ${role}`,
    role,
    department_id: role === 'hr' ? 'DEPT_HR' : 'DEPT_SALES',
    department_name: role === 'hr' ? 'Nhân sự' : 'Kinh doanh',
    position: role,
    manager_id: null,
    manager_name: null,
    start_date: '2024-01-01',
    annual_leave_balance: 12,
    used_annual_leave: 2,
    remaining_annual_leave: 10,
    employment_status: 'active',
    email: `${role}@company.vn`,
    phone: '0901234567',
    must_change_password: false,
    permissions: permissions ?? DEFAULT_ROLE_PERMISSIONS[role],
    allowed_screens: [],
  };
}

describe('RBAC 5-Role Frontend Completion: PermissionGuard, Revocation, Role Switching & Route Protection', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          period: '2026-10',
          role: 'hr',
          total: 2,
          can_edit: true,
          kpis: {
            total_employees: 80,
            total_work_hours: 1000,
            present_days: 100,
            on_time_days: 95,
            on_time_rate: 95,
            late_days: 5,
            late_rate: 5,
            leave_days: 2,
            absent_days: 0,
            missing_punch_days: 0,
            pending_leaves: 1,
            open_anomalies: 1,
            high_anomalies: 0,
            remaining_annual_leave: 10,
            total_accounts: 80,
            active_accounts: 80,
            locked_accounts: 0,
            roles_count: 5,
            permissions_count: 44,
            activity_logs_count: 10,
            query_audit_count: 5,
            blocked_query_count: 0,
            rag_documents_count: 3,
            rag_chunks_count: 3,
            kiosk_devices_total: 2,
            kiosk_devices_active: 2,
          },
          status_distribution: [],
          department_chart: [],
          monthly_trend: [],
          top_alerts: [],
          calendar_days: [],
          accounts_by_role: [],
          recent_security_events: [],
          items: [
            {
              employee_id: 'NV007',
              full_name: 'Nhân viên Sales',
              department_id: 'DEPT_SALES',
              department_name: 'Kinh doanh',
              position: 'Sales',
              manager_id: 'NV001',
              manager_name: 'Trưởng phòng',
              start_date: '2024-01-01',
              annual_leave_balance: 12,
              used_annual_leave: 2,
              remaining_annual_leave: 10,
              role: 'employee',
              employment_status: 'active',
              email: 'nv007@company.vn',
              phone: '0900000007',
            },
            {
              employee_id: 'NV080',
              full_name: 'Nguyễn Hải Đăng',
              department_id: 'DEPT_OPS',
              department_name: 'Vận hành',
              position: 'System Admin',
              manager_id: null,
              manager_name: null,
              start_date: '2023-01-01',
              annual_leave_balance: 12,
              used_annual_leave: 0,
              remaining_annual_leave: 12,
              role: 'admin',
              employment_status: 'active',
              email: 'admin@company.vn',
              phone: '0901000080',
            },
          ],
        }),
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('honors revoked empty permissions [] without falling back to default permissions', () => {
    const revokedUser = makeUser('employee', []);
    expect(resolvePermissions(revokedUser).size).toBe(0);
    expect(getDefaultHomePath(revokedUser)).toBe('/dashboard');

    render(
      <AuthProvider initialTestUser={revokedUser}>
        <MemoryRouter initialEntries={['/dashboard']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).queryAllByRole('link')).toHaveLength(0);
    expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
  });

  it('PermissionGuard renders children only when permission and role match, else renders fallback', () => {
    const { unmount } = render(
      <AuthProvider initialTestUser={makeUser('executive')}>
        <PermissionGuard permission="attendance.adjust" roles={['hr']} fallback={<span>NO_ACCESS</span>}>
          <button type="button">Điều chỉnh công</button>
        </PermissionGuard>
      </AuthProvider>
    );
    expect(screen.getByText('NO_ACCESS')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Điều chỉnh công' })).not.toBeInTheDocument();
    unmount();

    render(
      <AuthProvider initialTestUser={makeUser('hr')}>
        <PermissionGuard permission="attendance.adjust" roles={['hr']} fallback={<span>NO_ACCESS</span>}>
          <button type="button">Điều chỉnh công</button>
        </PermissionGuard>
      </AuthProvider>
    );
    expect(screen.getByRole('button', { name: 'Điều chỉnh công' })).toBeInTheDocument();
    expect(screen.queryByText('NO_ACCESS')).not.toBeInTheDocument();
  });

  it('blocks unauthorized direct URL routes across all 5 roles cleanly', () => {
    const forbiddenCases: Array<[UserRole, string]> = [
      ['employee', '/reports'],
      ['employee', '/admin/employees'],
      ['employee', '/admin/import'],
      ['employee', '/admin/rbac'],
      ['manager', '/admin/import'],
      ['manager', '/admin/accounts'],
      ['manager', '/admin/config'],
      ['hr', '/admin/system'],
      ['hr', '/admin/rbac'],
      ['hr', '/admin/config'],
      ['hr', '/admin/kiosk'],
      ['executive', '/attendance'],
      ['executive', '/admin/import'],
      ['executive', '/admin/employees'],
      ['executive', '/admin/accounts'],
      ['executive', '/admin/rbac'],
      ['admin', '/dashboard'],
      ['admin', '/attendance'],
      ['admin', '/leaves'],
      ['admin', '/anomalies'],
      ['admin', '/reports'],
      ['admin', '/assistant'],
      ['admin', '/admin/import'],
      ['admin', '/admin/employees'],
    ];

    for (const [role, path] of forbiddenCases) {
      const { unmount } = render(
        <AuthProvider initialTestUser={makeUser(role)}>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
          </MemoryRouter>
        </AuthProvider>
      );
      expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
      unmount();
    }
  });

  it('handles unknown/invalid role safely without white screen or crash', () => {
    expect(getDataScopeLabel('invalid_role')).toBe('Không xác định');
    const badRoleUser = makeUser('employee', []);
    (badRoleUser as unknown as { role: string }).role = 'unknown_role';

    render(
      <AuthProvider initialTestUser={badRoleUser}>
        <MemoryRouter initialEntries={['/dashboard']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );
    expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
    expect(screen.getByText('Không xác định')).toBeInTheDocument();
  });

  it('updates sidebar and data scope cleanly when switching across all 5 roles', () => {
    const checks: Array<{ role: UserRole; expectedLink: string; hiddenLink: string; scope: string }> = [
      { role: 'employee', expectedLink: 'Chấm công', hiddenLink: 'Báo cáo', scope: 'Dữ liệu cá nhân' },
      { role: 'manager', expectedLink: 'Báo cáo', hiddenLink: 'Nhập dữ liệu', scope: 'Phòng ban của tôi' },
      { role: 'hr', expectedLink: 'Nhập dữ liệu', hiddenLink: 'Phân quyền', scope: 'Toàn công ty' },
      { role: 'executive', expectedLink: 'Phân tích phòng ban', hiddenLink: 'Quản lý tài khoản', scope: 'Toàn công ty' },
      { role: 'admin', expectedLink: 'Phân quyền', hiddenLink: 'Đơn nghỉ phép', scope: 'Quản trị hệ thống' },
    ];

    for (const c of checks) {
      const { unmount } = render(
        <AuthProvider initialTestUser={makeUser(c.role)}>
          <MemoryRouter initialEntries={[getDefaultHomePath(makeUser(c.role))]}>
            <AppRoutes />
          </MemoryRouter>
        </AuthProvider>
      );
      const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
      expect(within(nav).getByRole('link', { name: c.expectedLink })).toBeInTheDocument();
      expect(within(nav).queryByRole('link', { name: c.hiddenLink })).not.toBeInTheDocument();
      expect(screen.getByText(c.scope)).toBeInTheDocument();
      unmount();
    }
  });

  it('hides HR write buttons on EmployeesPage for Manager and protects Admin rows for HR', async () => {
    // 1. Manager sees read-only EmployeesPage without "Thêm nhân viên"
    const { unmount } = render(
      <AuthProvider initialTestUser={makeUser('manager')}>
        <MemoryRouter initialEntries={['/admin/employees']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );
    expect(await screen.findByText('Nhân viên Sales', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Thêm nhân viên/i })).not.toBeInTheDocument();
    unmount();

    // 2. HR sees "Thêm nhân viên" and "Được bảo vệ" badge on Admin row NV080
    render(
      <AuthProvider initialTestUser={makeUser('hr')}>
        <MemoryRouter initialEntries={['/admin/employees']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );
    expect(await screen.findByRole('button', { name: /Thêm nhân viên/i }, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Được bảo vệ')).toBeInTheDocument(), { timeout: 4000 });
  });
});
