import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import { AppRoutes } from '../App';

function renderUnauthenticated(initialRoute = '/') {
  return render(
    <AuthProvider initialTestUser={null}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>
  );
}

describe('Enterprise SaaS LoginPage Redesign', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders split-screen branding, tagline, 3 benefits and welcome heading', () => {
    renderUnauthenticated();
    expect(screen.getAllByText('HR Attendance Copilot').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Smarter Attendance. Better Workforce.').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Chào mừng trở lại!')).toBeInTheDocument();
    expect(screen.getAllByText('Phát hiện bất thường').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('AI phân tích dữ liệu').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Báo cáo tự động').length).toBeGreaterThanOrEqual(1);
    // Forgot password must NOT appear when backend has no reset flow
    expect(screen.queryByText(/Quên mật khẩu/i)).not.toBeInTheDocument();
  });

  it('validates required fields and email format in Vietnamese', async () => {
    renderUnauthenticated();
    const submitBtn = screen.getByRole('button', { name: /Đăng nhập hệ thống/i });

    fireEvent.click(submitBtn);
    expect(await screen.findByText('Vui lòng nhập email đăng nhập.')).toBeInTheDocument();
    expect(screen.getByText('Vui lòng nhập mật khẩu.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Email doanh nghiệp/i), {
      target: { value: 'invalid-email' },
    });
    fireEvent.change(screen.getByLabelText(/^Mật khẩu/i), {
      target: { value: 'secret123' },
    });
    fireEvent.click(submitBtn);
    expect(await screen.findByText(/Định dạng email không hợp lệ/i)).toBeInTheDocument();
  });

  it('toggles password visibility with Show/Hide button', () => {
    renderUnauthenticated();
    const passwordInput = screen.getByLabelText(/^Mật khẩu/i) as HTMLInputElement;
    expect(passwordInput.type).toBe('password');

    const toggleBtn = screen.getByRole('button', { name: 'Hiện mật khẩu' });
    fireEvent.click(toggleBtn);
    expect(passwordInput.type).toBe('text');
    expect(screen.getByRole('button', { name: 'Ẩn mật khẩu' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Ẩn mật khẩu' }));
    expect(passwordInput.type).toBe('password');
  });

  it('displays clear Vietnamese error message when credentials are wrong', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Tên đăng nhập hoặc mật khẩu không chính xác.' }),
      })
    );

    renderUnauthenticated();
    fireEvent.change(screen.getByLabelText(/Email doanh nghiệp/i), {
      target: { value: 'hr@company.vn' },
    });
    fireEvent.change(screen.getByLabelText(/^Mật khẩu/i), {
      target: { value: 'wrongpass' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Đăng nhập hệ thống/i }));

    expect(
      await screen.findByText('Tên đăng nhập hoặc mật khẩu không chính xác.')
    ).toBeInTheDocument();
  });

  it('toggles collapsible DEV demo accounts with HR Admin, Manager, Employee badges and fills email without bypassing auth', async () => {
    renderUnauthenticated();
    const toggleDemo = screen.getByRole('button', { name: /Trải nghiệm tài khoản demo/i });
    expect(toggleDemo).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('hr@company.vn')).not.toBeInTheDocument();

    fireEvent.click(toggleDemo);
    expect(toggleDemo).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('HR Admin')).toBeInTheDocument();
    expect(screen.getByText('Manager')).toBeInTheDocument();
    expect(screen.getByText('Employee')).toBeInTheDocument();

    // Selecting demo without VITE_DEV_DEMO_PASSWORD fills email only (zero hardcoded password)
    fireEvent.click(screen.getByText('manager.sales@company.vn'));
    const emailInput = screen.getByLabelText(/Email doanh nghiệp/i) as HTMLInputElement;
    expect(emailInput.value).toBe('manager.sales@company.vn');
    expect(await screen.findByText(/Đã điền email manager\.sales@company\.vn/i)).toBeInTheDocument();
  });

  it('redirects to Dashboard after successful real API login', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/auth/login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            access_token: 'mock-jwt-token',
            user: {
              user_id: 'USR002',
              username: 'hr@company.vn',
              employee_id: 'NV002',
              full_name: 'Nguyễn Thị Mai',
              role: 'hr',
              department_id: 'DEPT_HR',
              department_name: 'Nhân sự',
              position: 'Trưởng bộ phận Nhân sự',
              start_date: '2022-08-15',
              annual_leave_balance: 12,
              used_annual_leave: 0,
              remaining_annual_leave: 12,
              employment_status: 'active',
              must_change_password: false,
              allowed_screens: [
                'dashboard', 'attendance', 'leaves', 'anomalies', 'assistant',
                'reports', 'profile', 'import', 'employees', 'accounts',
              ],
            },
          }),
        });
      }
      return Promise.resolve({
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
            remaining_annual_leave: 12,
          },
          status_distribution: [],
          department_chart: [],
          top_alerts: [],
          calendar_days: [],
          items: [],
          total: 0,
        }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderUnauthenticated('/admin/accounts');
    fireEvent.change(screen.getByLabelText(/Email doanh nghiệp/i), {
      target: { value: 'hr@company.vn' },
    });
    fireEvent.change(screen.getByLabelText(/^Mật khẩu/i), {
      target: { value: 'ValidPass123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Đăng nhập hệ thống/i }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Tổng quan' })).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.objectContaining({ method: 'POST' })
    );
  });
});
