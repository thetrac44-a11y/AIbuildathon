import { NavGroupTitle, NavItem, UserRole } from '../types/navigation';

export const ALLOW_MANAGER_EMPLOYEE_READ =
  (import.meta.env?.VITE_ALLOW_MANAGER_EMPLOYEE_READ ?? 'true') !== 'false';

export const SITEMAP_SCREENS: NavItem[] = [
  {
    id: 'face-attendance', code: '11', title: 'Máy chấm công khuôn mặt',
    path: '/face-attendance', group: 'Quản trị nhân sự', iconName: 'Clock',
    allowedRoles: ['hr'], syncPeriodFilter: false,
  },
  {
    id: 'dashboard',
    code: '01',
    title: 'Tổng quan',
    path: '/dashboard',
    group: 'Không gian làm việc',
    iconName: 'LayoutDashboard',
    allowedRoles: ['employee', 'manager', 'hr'],
    syncPeriodFilter: true,
  },
  {
    id: 'attendance',
    code: '02',
    title: 'Chấm công',
    path: '/attendance',
    group: 'Không gian làm việc',
    iconName: 'Clock',
    allowedRoles: ['employee', 'manager', 'hr'],
    syncPeriodFilter: true,
  },
  {
    id: 'leaves',
    code: '03',
    title: 'Đơn nghỉ phép',
    path: '/leaves',
    group: 'Không gian làm việc',
    iconName: 'CalendarDays',
    allowedRoles: ['employee', 'manager', 'hr'],
    syncPeriodFilter: true,
  },
  {
    id: 'anomalies',
    code: '04',
    title: 'Cảnh báo bất thường',
    path: '/anomalies',
    group: 'Không gian làm việc',
    iconName: 'AlertTriangle',
    allowedRoles: ['employee', 'manager', 'hr'],
    syncPeriodFilter: true,
  },
  {
    id: 'assistant',
    code: '05',
    title: 'Hỏi đáp AI',
    path: '/assistant',
    group: 'Không gian làm việc',
    iconName: 'Sparkles',
    allowedRoles: ['employee', 'manager', 'hr'],
    syncPeriodFilter: false,
  },
  {
    id: 'reports',
    code: '06',
    title: 'Báo cáo',
    path: '/reports',
    group: 'Không gian làm việc',
    iconName: 'FileSpreadsheet',
    allowedRoles: ['manager', 'hr'],
    syncPeriodFilter: true,
  },
  {
    id: 'profile',
    code: '07',
    title: 'Hồ sơ cá nhân',
    path: '/profile',
    group: 'Cá nhân',
    iconName: 'UserCircle',
    allowedRoles: ['employee', 'manager', 'hr'],
    syncPeriodFilter: false,
  },
  {
    id: 'import',
    code: '08',
    title: 'Nhập dữ liệu',
    path: '/admin/import',
    group: 'Quản trị nhân sự',
    iconName: 'UploadCloud',
    allowedRoles: ['hr'],
    syncPeriodFilter: false,
  },
  {
    id: 'employees',
    code: '09',
    title: 'Quản lý nhân viên',
    path: '/admin/employees',
    group: 'Quản trị nhân sự',
    iconName: 'Users',
    allowedRoles: ALLOW_MANAGER_EMPLOYEE_READ ? ['hr', 'manager'] : ['hr'],
    syncPeriodFilter: false,
  },
  {
    id: 'accounts',
    code: '10',
    title: 'Quản lý tài khoản',
    path: '/admin/accounts',
    group: 'Quản trị nhân sự',
    iconName: 'ShieldCheck',
    allowedRoles: ['hr'],
    syncPeriodFilter: false,
  },
];

export const NAV_GROUP_ORDER: NavGroupTitle[] = [
  'Không gian làm việc',
  'Cá nhân',
  'Quản trị nhân sự',
];

export function canAccessScreen(
  role: UserRole,
  screen: NavItem,
  allowManagerEmployeeRead = ALLOW_MANAGER_EMPLOYEE_READ
): boolean {
  if (screen.id === 'employees') {
    return role === 'hr' || (allowManagerEmployeeRead && role === 'manager');
  }
  return screen.allowedRoles.includes(role);
}

export function getVisibleNavGroups(
  role: UserRole,
  allowManagerEmployeeRead = ALLOW_MANAGER_EMPLOYEE_READ
): { group: NavGroupTitle; items: NavItem[] }[] {
  return NAV_GROUP_ORDER.map((groupName) => ({
    group: groupName,
    items: SITEMAP_SCREENS.filter(
      (item) => item.group === groupName && canAccessScreen(role, item, allowManagerEmployeeRead)
    ),
  })).filter((g) => g.items.length > 0);
}
