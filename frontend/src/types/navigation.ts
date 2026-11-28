export type UserRole = 'employee' | 'manager' | 'hr' | 'executive' | 'admin';

export type NavGroupTitle =
  | 'Không gian làm việc'
  | 'Quản trị nhân sự'
  | 'Hệ thống'
  | 'Quản trị'
  | 'AI'
  | 'Face Kiosk'
  | 'Cá nhân';

export type NavIconName =
  | 'LayoutDashboard'
  | 'Clock'
  | 'CalendarDays'
  | 'AlertTriangle'
  | 'Sparkles'
  | 'FileSpreadsheet'
  | 'UserCircle'
  | 'UploadCloud'
  | 'Users'
  | 'ShieldCheck'
  | 'BarChart3'
  | 'ServerCog'
  | 'KeyRound'
  | 'ScrollText'
  | 'BookOpen'
  | 'Settings'
  | 'Camera'
  | 'SlidersHorizontal';

export interface NavItem {
  id: string;
  code: string;
  title: string;
  roleTitleOverrides?: Partial<Record<UserRole, string>>;
  path: string;
  group: NavGroupTitle;
  iconName: NavIconName;
  permission?: string;
  anyPermissions?: string[];
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
