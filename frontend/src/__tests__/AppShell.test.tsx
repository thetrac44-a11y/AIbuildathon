import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, AuthUser } from '../context/AuthContext';
import { DEFAULT_ROLE_PERMISSIONS } from '../config/navigation';
import { AppRoutes } from '../App';
import { UserRole } from '../types/navigation';

function makeTestUser(role: UserRole): AuthUser {
  const empMap: Record<UserRole, { id: string; name: string; deptId: string; dept: string; pos: string }> = {
    employee: { id: 'NV007', name: 'Lê Minh Nhân Viên', deptId: 'DEPT_SALES', dept: 'Kinh doanh', pos: 'Nhân viên Kinh doanh' },
    manager: { id: 'NV001', name: 'Nguyễn Văn Trưởng Phòng', deptId: 'DEPT_SALES', dept: 'Kinh doanh', pos: 'Trưởng phòng Kinh doanh' },
    hr: { id: 'NV002', name: 'Trần Thị HR', deptId: 'DEPT_HR', dept: 'Nhân sự', pos: 'Trưởng phòng Nhân sự' },
    executive: { id: 'NV079', name: 'Trần Minh Quang', deptId: 'DEPT_OPS', dept: 'Vận hành', pos: 'Giám đốc Điều hành' },
    admin: { id: 'NV080', name: 'Nguyễn Hải Đăng', deptId: 'DEPT_OPS', dept: 'Vận hành', pos: 'Quản trị viên Hệ thống' },
  };
  const info = empMap[role];
  return {
    user_id: `USR-${role.toUpperCase()}`,
    username: `${role}@company.vn`,
    employee_id: info.id,
    full_name: info.name,
    role,
    department_id: info.deptId,
    department_name: info.dept,
    position: info.pos,
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
    permissions: DEFAULT_ROLE_PERMISSIONS[role],
    allowed_screens: [],
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

describe('AppShell, Auth & 5-Role Permission-Based Navigation', () => {
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
          database_engine: 'sqlite',
          health: 'healthy',
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
            total_accounts: 80,
            active_accounts: 80,
            locked_accounts: 0,
            roles_count: 5,
            permissions_count: 44,
            activity_logs_count: 10,
            query_audit_count: 5,
            blocked_query_count: 1,
            rag_documents_count: 3,
            rag_chunks_count: 3,
            kiosk_devices_total: 2,
            kiosk_devices_active: 2,
          },
          status_distribution: [
            { name: 'Đúng giờ', value: 1580 },
            { name: 'Đi muộn', value: 70 },
          ],
          department_chart: [],
          monthly_trend: [],
          top_alerts: [],
          calendar_days: [],
          accounts_by_role: [],
          recent_security_events: [],
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

  it('shows HR business navigation and hides Admin system-only menus', async () => {
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
    // HR must NOT see Admin-only system controls
    expect(within(nav).queryByRole('link', { name: 'System Dashboard' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Phân quyền' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Cấu hình hệ thống' })).not.toBeInTheDocument();
    expect(screen.getByText('Toàn công ty')).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('hides Reports and HR Admin screens for Employee role and shows personal Data Scope', async () => {
    renderWithUser(makeTestUser('employee'));
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).getByRole('link', { name: 'Tổng quan' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Hồ sơ cá nhân' })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Báo cáo' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Quản lý nhân viên' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Quản lý tài khoản' })).not.toBeInTheDocument();
    expect(screen.getByText('Dữ liệu cá nhân')).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('shows Reports & Employees and hides Import & Accounts for Manager role', async () => {
    renderWithUser(makeTestUser('manager'));
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).getByRole('link', { name: 'Báo cáo' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Quản lý nhân viên' })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Quản lý tài khoản' })).not.toBeInTheDocument();
    expect(screen.getByText('Phòng ban của tôi')).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('renders exact Executive sidebar and hides Account, RBAC, System Config, and Import Excel', async () => {
    renderWithUser(makeTestUser('executive'), '/dashboard');
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).getByRole('link', { name: 'Tổng quan điều hành' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Phân tích phòng ban' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Cảnh báo R1-R8' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Báo cáo' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Hỏi đáp AI' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Đơn cần phê duyệt' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Hồ sơ cá nhân' })).toBeInTheDocument();

    expect(within(nav).queryByRole('link', { name: 'Quản lý tài khoản' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Phân quyền' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Cấu hình hệ thống' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(screen.getByText('Toàn công ty')).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('renders exact Admin technical sidebar and hides HR business menus', async () => {
    renderWithUser(makeTestUser('admin'), '/admin/system');
    const nav = screen.getByRole('navigation', { name: 'Điều hướng chính' });
    expect(within(nav).getByRole('link', { name: 'System Dashboard' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Quản lý tài khoản' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Phân quyền' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Nhật ký kiểm toán' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Cấu hình hệ thống' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Kho tài liệu RAG' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Thiết bị' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Cấu hình' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Hồ sơ cá nhân' })).toBeInTheDocument();

    // Admin must NOT see HR business screens by default
    expect(within(nav).queryByRole('link', { name: 'Chấm công' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Đơn nghỉ phép' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Cảnh báo bất thường' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Quản lý nhân viên' })).not.toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Báo cáo' })).not.toBeInTheDocument();
    expect(screen.getByText('Quản trị hệ thống')).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it('blocks unauthorized direct URL navigation with 403 message across roles', () => {
    const { unmount } = renderWithUser(makeTestUser('employee'), '/admin/accounts');
    expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
    unmount();

    const r2 = renderWithUser(makeTestUser('admin'), '/attendance');
    expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
    r2.unmount();

    renderWithUser(makeTestUser('executive'), '/admin/rbac');
    expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
  });
});
