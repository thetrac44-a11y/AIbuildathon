import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, AuthUser } from '../context/AuthContext';
import { AppRoutes } from '../App';
import { UserRole } from '../types/navigation';

function makeTestUser(role: UserRole): AuthUser {
  const screenMap: Record<UserRole, string[]> = {
    employee: ['dashboard', 'attendance', 'leaves', 'anomalies', 'assistant', 'profile'],
    manager: ['dashboard', 'attendance', 'leaves', 'anomalies', 'assistant', 'reports', 'profile', 'employees'],
    hr: ['dashboard', 'attendance', 'leaves', 'anomalies', 'assistant', 'reports', 'profile', 'import', 'employees', 'accounts'],
  };
  return {
    user_id: `USR-${role.toUpperCase()}`,
    username: `${role}@company.vn`,
    employee_id: role === 'hr' ? 'NV002' : role === 'manager' ? 'NV001' : 'NV007',
    full_name: role === 'hr' ? 'Trần Thị HR' : role === 'manager' ? 'Nguyễn Văn Trưởng Phòng' : 'Lê Minh Nhân Viên',
    role,
    department_id: role === 'hr' ? 'DEPT_HR' : 'DEPT_SALES',
    department_name: role === 'hr' ? 'Nhân sự' : 'Kinh doanh',
    position: role === 'hr' ? 'Trưởng phòng Nhân sự' : role === 'manager' ? 'Trưởng phòng Kinh doanh' : 'Nhân viên Kinh doanh',
    manager_id: null,
    manager_name: null,
    start_date: '2024-01-15',
    annual_leave_balance: 12,
    used_annual_leave: 2,
    remaining_annual_leave: 10,
    employment_status: 'active',
    email: `${role}@company.vn`,
    phone: '0901234567',
    must_change_password: false,
    allowed_screens: screenMap[role],
  };
}

function renderWithUser(user: AuthUser | null, initialRoute = '/dashboard') {
  return render(
    <AuthProvider initialTestUser={user}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>
  );
}

describe('AppShell, Auth & Role-based Navigation (10 Screens)', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          period: '2026-10',
          role: 'hr',
          scope: { employee_id: null, department_id: null },
          kpis: {
            total_employees: 80,
            total_work_hours: 13200,
            present_days: 1650,
            on_time_days: 1580,
            on_time_rate: 95.8,
            late_days: 70,
            late_rate: 4.2,
            leave_days: 35,
            absent_days: 4,
            missing_punch_days: 2,
            pending_leaves: 3,
            open_anomalies: 6,
            high_anomalies: 2,
            remaining_annual_leave: 10,
          },
          status_distribution: [
            { name: 'Đúng giờ', value: 1580 },
            { name: 'Đi muộn', value: 70 },
          ],
          department_chart: [],
          top_alerts: [],
          calendar_days: [],
          items: [],
          total: 0,
        }),
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders LoginPage when user is not authenticated', () => {
    renderWithUser(null);
    expect(screen.getByText(/Đăng nhập hệ thống/i)).toBeInTheDocument();
  });

  it('shows all 10 screens in sidebar for HR role', async () => {
    renderWithUser(makeTestUser('hr'));
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).getByRole('link', { name: 'Tổng quan' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Chấm công' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Đơn nghỉ phép' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Cảnh báo bất thường' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Hỏi đáp AI' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Báo cáo' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Hồ sơ cá nhân' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Nhập dữ liệu' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Quản lý nhân viên' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Quản lý tài khoản' })).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('hides Reports and HR Admin screens for Employee role', async () => {
    renderWithUser(makeTestUser('employee'));
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).getByRole('link', { name: 'Tổng quan' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Hồ sơ cá nhân' })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Báo cáo' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Quản lý nhân viên' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Quản lý tài khoản' })).not.toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('shows Reports & Employees and hides Import & Accounts for Manager role', async () => {
    renderWithUser(makeTestUser('manager'));
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).getByRole('link', { name: 'Báo cáo' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Quản lý nhân viên' })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Quản lý tài khoản' })).not.toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('blocks unauthorized direct URL navigation with 403 message', () => {
    renderWithUser(makeTestUser('employee'), '/admin/accounts');
    expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
  });
});
