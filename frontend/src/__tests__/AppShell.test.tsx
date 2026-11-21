import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DevAuthProvider } from '../context/DevAuthContext';
import { AppRoutes } from '../App';
import { UserRole } from '../types/navigation';

function renderWithRole(role: UserRole, initialRoute = '/dashboard') {
  return render(
    <DevAuthProvider initialRole={role}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <AppRoutes />
      </MemoryRouter>
    </DevAuthProvider>
  );
}

describe('Stage 1 AppShell & Role-based Navigation', () => {
  it('shows all 10 screens in sidebar for HR role', () => {
    renderWithRole('hr');
    expect(screen.getByRole('link', { name: 'Tổng quan' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Chấm công' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Đơn nghỉ phép' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Cảnh báo bất thường' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Hỏi đáp AI' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Báo cáo' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Hồ sơ cá nhân' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Nhập dữ liệu' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Quản lý nhân viên' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Quản lý tài khoản' })).toBeInTheDocument();
  });

  it('hides Reports and HR Admin screens for Employee role', () => {
    renderWithRole('employee');
    expect(screen.getByRole('link', { name: 'Tổng quan' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Hồ sơ cá nhân' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Báo cáo' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Quản lý nhân viên' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Quản lý tài khoản' })).not.toBeInTheDocument();
  });

  it('shows Reports and hides Import & Accounts for Manager role', () => {
    renderWithRole('manager');
    expect(screen.getByRole('link', { name: 'Báo cáo' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Nhập dữ liệu' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Quản lý tài khoản' })).not.toBeInTheDocument();
  });

  it('blocks unauthorized direct URL navigation with 403 message', () => {
    renderWithRole('employee', '/admin/accounts');
    expect(screen.getByText(/403 – Không có quyền truy cập/i)).toBeInTheDocument();
  });
});
