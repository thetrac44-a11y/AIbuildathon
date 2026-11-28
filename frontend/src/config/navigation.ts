import { NavGroupTitle, NavItem, UserRole } from '../types/navigation';

export const ALLOW_MANAGER_EMPLOYEE_READ =
  (import.meta.env?.VITE_ALLOW_MANAGER_EMPLOYEE_READ ?? 'true') !== 'false';

/**
 * Fallback canonical permission map mirroring backend/app/core/permissions.py.
 * In live sessions, permissions always come fresh from /api/auth/me (database RBAC).
 */
export const DEFAULT_ROLE_PERMISSIONS: Record<UserRole, string[]> = {
  employee: [
    'profile.read.self',
    'profile.update.self',
    'dashboard.self',
    'attendance.read.self',
    'attendance.face_checkin',
    'leave.create.self',
    'leave.read.self',
    'anomaly.read.self',
    'ai.ask.self',
  ],
  manager: [
    'profile.read.self',
    'profile.update.self',
    'dashboard.department',
    'attendance.read.self',
    'attendance.read.department',
    'attendance.face_checkin',
    'leave.create.self',
    'leave.read.self',
    'leave.read.department',
    'leave.approve.department',
    'employee.read.department',
    'anomaly.read.self',
    'anomaly.read.department',
    'anomaly.review',
    'report.read.department',
    'ai.ask.department',
  ],
  hr: [
    'profile.read.self',
    'profile.update.self',
    'dashboard.all',
    'attendance.read.all',
    'attendance.adjust',
    'attendance.face_checkin',
    'leave.create.self',
    'leave.read.all',
    'leave.approve.all',
    'employee.read.all',
    'employee.manage',
    'import.manage',
    'anomaly.read.all',
    'anomaly.review',
    'report.read.all',
    'ai.ask.all',
    'rag.manage',
    'document.manage',
    'policy.manage',
    'face.manage',
    'account.manage.business',
    'audit.read.business',
  ],
  executive: [
    'profile.read.self',
    'profile.update.self',
    'dashboard.all',
    'dashboard.executive',
    'attendance.read.all',
    'leave.read.all',
    'leave.approve.executive',
    'employee.read.all',
    'anomaly.read.all',
    'report.read.all',
    'ai.ask.all',
    'ai.strategy',
  ],
  admin: [
    'profile.read.self',
    'profile.update.self',
    'system.dashboard',
    'account.manage',
    'role.manage',
    'audit.read',
    'rag.manage',
    'document.manage',
    'system.manage',
    'kiosk.manage',
  ],
};

export interface PermissionSubject {
  role: UserRole;
  permissions?: string[];
}

export function resolvePermissions(subject: UserRole | PermissionSubject): Set<string> {
  if (typeof subject === 'string') {
    return new Set(DEFAULT_ROLE_PERMISSIONS[subject] ?? []);
  }
  if (subject.permissions && subject.permissions.length > 0) {
    return new Set(subject.permissions);
  }
  return new Set(DEFAULT_ROLE_PERMISSIONS[subject.role] ?? []);
}

export function hasPermission(
  subject: UserRole | PermissionSubject | null | undefined,
  permission: string
): boolean {
  if (!subject) return false;
  return resolvePermissions(subject).has(permission);
}

export function hasAnyPermission(
  subject: UserRole | PermissionSubject | null | undefined,
  permissions: string[]
): boolean {
  if (!subject) return false;
  const set = resolvePermissions(subject);
  return permissions.some((p) => set.has(p));
}

export const SITEMAP_SCREENS: NavItem[] = [
  // --- System Admin Landing ---
  {
    id: 'system_dashboard',
    code: '11',
    title: 'System Dashboard',
    path: '/admin/system',
    group: 'Hệ thống',
    iconName: 'ServerCog',
    permission: 'system.dashboard',
    allowedRoles: ['admin'],
    syncPeriodFilter: false,
  },

  // --- Workspace (Employee / Manager / HR / Executive) ---
  {
    id: 'dashboard',
    code: '01',
    title: 'Tổng quan',
    roleTitleOverrides: {
      executive: 'Tổng quan điều hành',
    },
    path: '/dashboard',
    group: 'Không gian làm việc',
    iconName: 'LayoutDashboard',
    anyPermissions: ['dashboard.self', 'dashboard.department', 'dashboard.all', 'dashboard.executive'],
    allowedRoles: ['employee', 'manager', 'hr', 'executive'],
    syncPeriodFilter: true,
  },
  {
    id: 'department_analytics',
    code: '17',
    title: 'Phân tích phòng ban',
    path: '/executive/departments',
    group: 'Không gian làm việc',
    iconName: 'BarChart3',
    permission: 'dashboard.executive',
    allowedRoles: ['executive'],
    syncPeriodFilter: true,
  },
  {
    id: 'attendance',
    code: '02',
    title: 'Chấm công',
    path: '/attendance',
    group: 'Không gian làm việc',
    iconName: 'Clock',
    anyPermissions: ['attendance.face_checkin', 'attendance.read.department', 'attendance.adjust'],
    allowedRoles: ['employee', 'manager', 'hr'],
    syncPeriodFilter: true,
  },
  {
    id: 'anomalies',
    code: '04',
    title: 'Cảnh báo bất thường',
    roleTitleOverrides: {
      executive: 'Cảnh báo R1-R8',
    },
    path: '/anomalies',
    group: 'Không gian làm việc',
    iconName: 'AlertTriangle',
    anyPermissions: ['anomaly.read.self', 'anomaly.read.department', 'anomaly.read.all'],
    allowedRoles: ['employee', 'manager', 'hr', 'executive'],
    syncPeriodFilter: true,
  },
  {
    id: 'reports',
    code: '06',
    title: 'Báo cáo',
    path: '/reports',
    group: 'Không gian làm việc',
    iconName: 'FileSpreadsheet',
    anyPermissions: ['report.read.department', 'report.read.all'],
    allowedRoles: ['manager', 'hr', 'executive'],
    syncPeriodFilter: true,
  },
  {
    id: 'assistant',
    code: '05',
    title: 'Hỏi đáp AI',
    path: '/assistant',
    group: 'Không gian làm việc',
    iconName: 'Sparkles',
    anyPermissions: ['ai.ask.self', 'ai.ask.department', 'ai.ask.all', 'ai.strategy'],
    allowedRoles: ['employee', 'manager', 'hr', 'executive'],
    syncPeriodFilter: false,
  },
  {
    id: 'leaves',
    code: '03',
    title: 'Đơn nghỉ phép',
    roleTitleOverrides: {
      executive: 'Đơn cần phê duyệt',
    },
    path: '/leaves',
    group: 'Không gian làm việc',
    iconName: 'CalendarDays',
    anyPermissions: ['leave.read.self', 'leave.read.department', 'leave.read.all', 'leave.approve.executive'],
    allowedRoles: ['employee', 'manager', 'hr', 'executive'],
    syncPeriodFilter: true,
  },

  // --- HR Business Administration ---
  {
    id: 'import',
    code: '08',
    title: 'Nhập dữ liệu',
    path: '/admin/import',
    group: 'Quản trị nhân sự',
    iconName: 'UploadCloud',
    permission: 'import.manage',
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
    anyPermissions: ['employee.read.department', 'employee.manage'],
    allowedRoles: ALLOW_MANAGER_EMPLOYEE_READ ? ['hr', 'manager'] : ['hr'],
    syncPeriodFilter: false,
  },

  // --- System & Security Governance (Admin + scoped HR items) ---
  {
    id: 'accounts',
    code: '10',
    title: 'Quản lý tài khoản',
    path: '/admin/accounts',
    group: 'Quản trị',
    iconName: 'ShieldCheck',
    anyPermissions: ['account.manage', 'account.manage.business'],
    allowedRoles: ['admin', 'hr'],
    syncPeriodFilter: false,
  },
  {
    id: 'rbac',
    code: '12',
    title: 'Phân quyền',
    path: '/admin/rbac',
    group: 'Quản trị',
    iconName: 'KeyRound',
    permission: 'role.manage',
    allowedRoles: ['admin'],
    syncPeriodFilter: false,
  },
  {
    id: 'audit',
    code: '13',
    title: 'Nhật ký kiểm toán',
    path: '/admin/audit',
    group: 'Quản trị',
    iconName: 'ScrollText',
    anyPermissions: ['audit.read', 'audit.read.business'],
    allowedRoles: ['admin', 'hr'],
    syncPeriodFilter: false,
  },
  {
    id: 'system_config',
    code: '15',
    title: 'Cấu hình hệ thống',
    path: '/admin/config',
    group: 'Quản trị',
    iconName: 'Settings',
    permission: 'system.manage',
    allowedRoles: ['admin'],
    syncPeriodFilter: false,
  },

  // --- AI Knowledge Base ---
  {
    id: 'rag',
    code: '14',
    title: 'Kho tài liệu RAG',
    path: '/admin/rag',
    group: 'AI',
    iconName: 'BookOpen',
    permission: 'rag.manage',
    allowedRoles: ['admin', 'hr'],
    syncPeriodFilter: false,
  },

  // --- Face Kiosk (Admin technical management) ---
  {
    id: 'kiosk_devices',
    code: '16',
    title: 'Thiết bị',
    path: '/admin/kiosk',
    group: 'Face Kiosk',
    iconName: 'Camera',
    permission: 'kiosk.manage',
    allowedRoles: ['admin'],
    syncPeriodFilter: false,
  },
  {
    id: 'kiosk_config',
    code: '18',
    title: 'Cấu hình',
    path: '/admin/kiosk/config',
    group: 'Face Kiosk',
    iconName: 'SlidersHorizontal',
    permission: 'kiosk.manage',
    allowedRoles: ['admin'],
    syncPeriodFilter: false,
  },

  // --- Personal ---
  {
    id: 'profile',
    code: '07',
    title: 'Hồ sơ cá nhân',
    path: '/profile',
    group: 'Cá nhân',
    iconName: 'UserCircle',
    permission: 'profile.read.self',
    allowedRoles: ['employee', 'manager', 'hr', 'executive', 'admin'],
    syncPeriodFilter: false,
  },
];

export const NAV_GROUP_ORDER: NavGroupTitle[] = [
  'Hệ thống',
  'Không gian làm việc',
  'Quản trị nhân sự',
  'Quản trị',
  'AI',
  'Face Kiosk',
  'Cá nhân',
];

export function getScreenTitle(screen: NavItem, role: UserRole): string {
  return screen.roleTitleOverrides?.[role] ?? screen.title;
}

export function getDefaultHomePath(subject: UserRole | PermissionSubject): string {
  if (hasPermission(subject, 'system.dashboard') && !hasPermission(subject, 'dashboard.all')) {
    return '/admin/system';
  }
  return '/dashboard';
}

export function getDataScopeLabel(role: UserRole): string {
  switch (role) {
    case 'employee':
      return 'Dữ liệu cá nhân';
    case 'manager':
      return 'Phòng ban của tôi';
    case 'hr':
      return 'Toàn công ty';
    case 'executive':
      return 'Toàn công ty';
    case 'admin':
      return 'Quản trị hệ thống';
  }
}

export function canAccessScreen(
  subject: UserRole | PermissionSubject,
  screen: NavItem,
  allowManagerEmployeeRead = ALLOW_MANAGER_EMPLOYEE_READ
): boolean {
  const role = typeof subject === 'string' ? subject : subject.role;
  if (screen.id === 'employees' && role === 'manager' && !allowManagerEmployeeRead) {
    return false;
  }
  const perms = resolvePermissions(subject);
  if (screen.permission) {
    return perms.has(screen.permission);
  }
  if (screen.anyPermissions && screen.anyPermissions.length > 0) {
    return screen.anyPermissions.some((p) => perms.has(p));
  }
  return screen.allowedRoles.includes(role);
}

export function getVisibleNavGroups(
  subject: UserRole | PermissionSubject,
  allowManagerEmployeeRead = ALLOW_MANAGER_EMPLOYEE_READ
): { group: NavGroupTitle; items: NavItem[] }[] {
  return NAV_GROUP_ORDER.map((groupName) => ({
    group: groupName,
    items: SITEMAP_SCREENS.filter(
      (item) => item.group === groupName && canAccessScreen(subject, item, allowManagerEmployeeRead)
    ),
  })).filter((g) => g.items.length > 0);
}
