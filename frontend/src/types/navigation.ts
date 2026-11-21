export type UserRole = 'employee' | 'manager' | 'hr';

export type NavGroupTitle = 'Không gian làm việc' | 'Cá nhân' | 'Quản trị nhân sự';

export interface NavItem {
  id: string;
  code: string;
  title: string;
  path: string;
  group: NavGroupTitle;
  iconName:
    | 'LayoutDashboard'
    | 'Clock'
    | 'CalendarDays'
    | 'AlertTriangle'
    | 'Sparkles'
    | 'FileSpreadsheet'
    | 'UserCircle'
    | 'UploadCloud'
    | 'Users'
    | 'ShieldCheck';
  allowedRoles: UserRole[];
  syncPeriodFilter?: boolean;
}

export interface DevUserAccount {
  userId: string;
  employeeId: string;
  fullName: string;
  role: UserRole;
  departmentId: string;
  departmentName: string;
  position: string;
  managerName: string;
}
