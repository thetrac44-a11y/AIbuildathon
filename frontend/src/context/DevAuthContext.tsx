import React, { createContext, useContext, useState } from 'react';
import { DevUserAccount, UserRole } from '../types/navigation';

/**
 * DEV-ONLY AUTHENTICATION CONTEXT (Stage 1 - Prompt 1)
 * Used purely in Stage 1 to test AppShell, Sidebar role visibility, and RouteGuards
 * across the 3 roles (employee / manager / hr).
 * Real server-side authentication & RBAC enforcement will replace this in Stage 3 (Prompt 3).
 */
export const DEV_DEMO_ACCOUNTS: Record<UserRole, DevUserAccount> = {
  hr: {
    userId: 'usr-hr-01',
    employeeId: 'NV002',
    fullName: 'Nguyễn Thị Mai',
    role: 'hr',
    departmentId: 'DEPT_HR',
    departmentName: 'Nhân sự',
    position: 'Chuyên viên Nhân sự (HR)',
    managerName: 'Ban Giám đốc',
  },
  manager: {
    userId: 'usr-mgr-01',
    employeeId: 'NV001',
    fullName: 'Nguyễn Văn B',
    role: 'manager',
    departmentId: 'DEPT_SALES',
    departmentName: 'Kinh doanh',
    position: 'Trưởng phòng Kinh doanh',
    managerName: 'Ban Giám đốc',
  },
  employee: {
    userId: 'usr-emp-07',
    employeeId: 'NV007',
    fullName: 'Nguyễn Văn A',
    role: 'employee',
    departmentId: 'DEPT_SALES',
    departmentName: 'Kinh doanh',
    position: 'Nhân viên Kinh doanh',
    managerName: 'Nguyễn Văn B',
  },
};

export const AVAILABLE_PERIODS = [
  { value: '2026-11', label: 'Tháng 11/2026' },
  { value: '2026-10', label: 'Tháng 10/2026' },
  { value: '2026-09', label: 'Tháng 09/2026' },
  { value: '2026-08', label: 'Tháng 08/2026' },
  { value: '2026-07', label: 'Tháng 07/2026' },
  { value: '2026-06', label: 'Tháng 06/2026' },
];

interface DevAuthContextValue {
  currentUser: DevUserAccount;
  setRole: (role: UserRole) => void;
  selectedPeriod: string;
  setSelectedPeriod: (period: string) => void;
  isDevMockAuth: boolean;
}

const DevAuthContext = createContext<DevAuthContextValue | undefined>(undefined);

export const DevAuthProvider: React.FC<{
  initialRole?: UserRole;
  children: React.ReactNode;
}> = ({ initialRole = 'hr', children }) => {
  const [role, setRoleState] = useState<UserRole>(initialRole);
  const [selectedPeriod, setSelectedPeriod] = useState<string>('2026-10');

  const value: DevAuthContextValue = {
    currentUser: DEV_DEMO_ACCOUNTS[role],
    setRole: setRoleState,
    selectedPeriod,
    setSelectedPeriod,
    isDevMockAuth: true,
  };

  return <DevAuthContext.Provider value={value}>{children}</DevAuthContext.Provider>;
};

export function useDevAuth(): DevAuthContextValue {
  const ctx = useContext(DevAuthContext);
  if (!ctx) {
    throw new Error('useDevAuth must be used inside a DevAuthProvider');
  }
  return ctx;
}
