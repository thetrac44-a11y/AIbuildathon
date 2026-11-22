import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, AuthUser } from '../context/AuthContext';
import { AppRoutes } from '../App';
import { DataTable } from '../components/ui/DataTable';
import { UserRole } from '../types/navigation';

function makeUser(role: UserRole): AuthUser {
  return {
    user_id: role === 'hr' ? 'USR002' : 'USR015',
    username: role === 'hr' ? 'hr@company.vn' : 'nv015@company.vn',
    employee_id: role === 'hr' ? 'NV002' : 'NV015',
    full_name: role === 'hr' ? 'Nguyễn Thị Mai' : 'Trần Minh Đức',
    role,
    department_id: role === 'hr' ? 'DEPT_HR' : 'DEPT_SALES',
    department_name: role === 'hr' ? 'Nhân sự' : 'Kinh doanh',
    position: role === 'hr' ? 'Trưởng bộ phận Nhân sự' : 'Chuyên viên Kinh doanh',
    manager_id: null,
    manager_name: 'Nguyễn Văn Bình',
    start_date: '2024-01-01',
    annual_leave_balance: 12,
    used_annual_leave: 0,
    remaining_annual_leave: 12,
    employment_status: 'active',
    must_change_password: false,
    allowed_screens:
      role === 'hr'
        ? ['dashboard', 'attendance', 'leaves', 'anomalies', 'assistant', 'reports', 'profile', 'import', 'employees', 'accounts']
        : ['dashboard', 'attendance', 'leaves', 'anomalies', 'assistant', 'profile'],
  };
}

describe('BUG-01 to BUG-10 Frontend Regression Suite', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('BUG-01 & BUG-09: AnomaliesPage syncs selectedPeriod by default and handles 404 direct URL cleanly', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/anomalies/999')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ detail: 'Không tìm thấy cảnh báo bất thường.' }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          total: 4,
          summary: { total: 4, open: 4, confirmed: 0, dismissed: 0, high: 0, medium: 2, low: 2 },
          items: [],
        }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <AuthProvider initialTestUser={makeUser('hr')}>
        <MemoryRouter initialEntries={['/anomalies/999']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    expect(await screen.findByText('Không tìm thấy cảnh báo bất thường.')).toBeInTheDocument();
    // Default list fetch must include period=2026-10 (BUG-01)
    const calledUrls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calledUrls.some((u) => u.includes('/anomalies?') && u.includes('period=2026-10'))).toBe(true);
  });

  it('BUG-02 & BUG-10: LeavesPage filters by selectedPeriod and displays approval timeline in modal', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/leaves/14')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            request: { request_id: 14 },
            timeline: [
              {
                id: 1,
                action: 'submit',
                note: 'Đưa người nhà đi viện',
                created_at: '2026-10-20 09:00:00',
                actor_username: 'nv016@company.vn',
                actor_name: 'Nguyễn Văn B',
              },
              {
                id: 2,
                action: 'reject',
                note: 'Phòng đang cao điểm cuối tháng',
                created_at: '2026-10-20 14:30:00',
                actor_username: 'manager.sales@company.vn',
                actor_name: 'Nguyễn Văn Bình',
              },
            ],
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          total: 1,
          period: '2026-10',
          kpis: { pending: 1, pending_all: 4, approved: 8, rejected: 1 },
          my_balance: { annual_leave_balance: 12, used_annual_leave: 0, remaining_annual_leave: 12 },
          items: [
            {
              request_id: 14,
              employee_id: 'NV016',
              full_name: 'Nguyễn Văn B',
              department_name: 'Kinh doanh',
              leave_type: 'personal',
              from_date: '2026-10-27',
              to_date: '2026-10-27',
              leave_days: 1,
              reason: 'Đưa người nhà đi viện',
              status: 'rejected',
              reviewed_by: 'NV001',
              decision_note: 'Phòng đang cao điểm cuối tháng',
              created_at: '2026-10-20 09:00:00',
              can_review: false,
              can_cancel: false,
            },
          ],
        }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <AuthProvider initialTestUser={makeUser('hr')}>
        <MemoryRouter initialEntries={['/leaves']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    expect(await screen.findByText('Đơn chờ duyệt (hiện hành)')).toBeInTheDocument();
    const calledUrls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calledUrls.some((u) => u.includes('/leaves?') && u.includes('period=2026-10'))).toBe(true);

    // Open detail modal and verify timeline from leave_approval_logs renders
    fireEvent.click(screen.getByRole('button', { name: 'Chi tiết' }));
    expect(await screen.findByText('Lịch sử xử lý & phê duyệt')).toBeInTheDocument();
    expect(await screen.findByText('Nguyễn Văn Bình')).toBeInTheDocument();
    expect(screen.getByText('Gửi đơn')).toBeInTheDocument();
  });

  it('BUG-03 & BUG-06: Dashboard separates anomaly & pending leave KPIs and flags missing punch on Employee calendar', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          period: '2026-09',
          role: 'employee',
          kpis: {
            total_employees: 1,
            total_work_hours: 144.0,
            present_days: 22,
            on_time_days: 22,
            on_time_rate: 100,
            late_days: 0,
            late_rate: 0,
            leave_days: 0,
            absent_days: 0,
            missing_punch_days: 4,
            pending_leaves: 0,
            pending_leaves_in_period: 0,
            open_anomalies: 1,
            high_anomalies: 0,
            remaining_annual_leave: 12,
          },
          status_distribution: [],
          department_chart: [],
          top_alerts: [],
          calendar_days: [
            {
              work_date: '2026-09-07',
              status: 'present',
              is_late: 0,
              late_minutes: 0,
              work_hours: 0,
              check_in: '2026-09-07 08:22:10',
              check_out: null,
            },
          ],
          items: [],
        }),
      })
    );

    render(
      <AuthProvider initialTestUser={makeUser('employee')}>
        <MemoryRouter initialEntries={['/dashboard']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    expect(await screen.findByText('Thiếu CC')).toBeInTheDocument();
    expect(screen.getByText(/Thiếu CC \(thiếu giờ vào\/ra\)/i)).toBeInTheDocument();
  });

  it('BUG-08: DataTable hides hardcoded Trang 1/1 for single page and shows real pagination for multi-page', () => {
    const onPageChange = vi.fn();
    const { rerender } = render(
      <DataTable
        columns={[{ key: 'name', header: 'Tên' }]}
        data={[{ id: '1', name: 'A' }]}
        rowKey={(r) => r.id}
        pagination={{ page: 1, pageSize: 25, totalCount: 1, onPageChange }}
      />
    );
    expect(screen.queryByText(/Trang 1 \/ 1/i)).not.toBeInTheDocument();
    expect(screen.getByText('Tổng số dòng: 1')).toBeInTheDocument();

    rerender(
      <DataTable
        columns={[{ key: 'name', header: 'Tên' }]}
        data={[{ id: '1', name: 'A' }]}
        rowKey={(r) => r.id}
        pagination={{ page: 1, pageSize: 25, totalCount: 60, onPageChange }}
      />
    );
    expect(screen.getByText('Trang 1 / 3')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Trang sau/i }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it('BUG-03: HR Dashboard shows separate cards for open anomalies and pending leaves', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          period: '2026-10',
          role: 'hr',
          kpis: {
            total_employees: 80,
            total_work_hours: 14368.5,
            present_days: 1729,
            on_time_days: 1634,
            on_time_rate: 94.51,
            late_days: 95,
            late_rate: 5.49,
            leave_days: 10,
            absent_days: 24,
            missing_punch_days: 0,
            pending_leaves: 4,
            pending_leaves_in_period: 1,
            open_anomalies: 4,
            high_anomalies: 0,
            remaining_annual_leave: 12,
          },
          status_distribution: [],
          department_chart: [],
          top_alerts: [],
          calendar_days: [],
          items: [],
        }),
      })
    );

    render(
      <AuthProvider initialTestUser={makeUser('hr')}>
        <MemoryRouter initialEntries={['/dashboard']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Cảnh báo bất thường mở')).toBeInTheDocument();
      expect(screen.getByText('Đơn nghỉ phép chờ duyệt')).toBeInTheDocument();
    });
  });

  it('BUG-12: ProfilePage avatar container has shrink-0 so it never squeezes on mobile 390x844', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => makeUser('employee'),
      })
    );

    render(
      <AuthProvider initialTestUser={makeUser('employee')}>
        <MemoryRouter initialEntries={['/profile']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    const avatar = await screen.findByTestId('profile-avatar');
    expect(avatar.className).toContain('w-14');
    expect(avatar.className).toContain('h-14');
    expect(avatar.className).toContain('shrink-0');
  });
});
