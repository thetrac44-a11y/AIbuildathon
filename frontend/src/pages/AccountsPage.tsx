import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  KeyRound,
  Lock,
  Plus,
  ShieldAlert,
  Unlock,
  UserCog,
  X,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { FilterBar } from '../components/ui/FilterBar';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

import { UserRole } from '../types/navigation';

interface AccountRow {
  user_id: string;
  username: string;
  employee_id: string;
  full_name: string;
  department_id: string;
  department_name: string;
  role: UserRole;
  is_active: number;
  employment_status: string;
  must_change_password: number;
  last_login_at: string | null;
  created_at: string;
}

interface EmployeeLite {
  employee_id: string;
  full_name: string;
  department_name: string;
  role: string;
}

interface AuditLogRow {
  id: number;
  actor_user_id: string;
  actor_username: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  before_json: string | null;
  after_json: string | null;
  created_at: string;
}

const ROLE_LABELS: Record<string, string> = {
  employee: 'Nhân viên',
  manager: 'Trưởng phòng',
  hr: 'Nhân sự (HR)',
  executive: 'Cấp lãnh đạo',
  admin: 'Quản trị hệ thống',
};

export const AccountsPage: React.FC = () => {
  const { showToast } = useAuth();
  const [section, setSection] = useState<'accounts' | 'audit'>('accounts');

  // Accounts state
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [assignableRoles, setAssignableRoles] = useState<UserRole[]>(['employee', 'manager', 'hr']);
  const [canManageAllRoles, setCanManageAllRoles] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState<string>('');
  const [roleFilter, setRoleFilter] = useState<string>('all');

  // Audit logs state
  const [auditLogs, setAuditLogs] = useState<AuditLogRow[]>([]);
  const [loadingAudit, setLoadingAudit] = useState<boolean>(false);
  const [selectedAudit, setSelectedAudit] = useState<AuditLogRow | null>(null);

  // Create account modal
  const [createOpen, setCreateOpen] = useState<boolean>(false);
  const [employees, setEmployees] = useState<EmployeeLite[]>([]);
  const [createForm, setCreateForm] = useState({
    employee_id: '',
    username: '',
    password: '',
    role: 'employee' as UserRole,
    must_change_password: true,
  });
  const [creating, setCreating] = useState<boolean>(false);

  // Edit role / reset password modal
  const [editTarget, setEditTarget] = useState<AccountRow | null>(null);
  const [editRole, setEditRole] = useState<UserRole>('employee');
  const [resetPassword, setResetPassword] = useState<string>('');
  const [forceChange, setForceChange] = useState<boolean>(true);
  const [savingEdit, setSavingEdit] = useState<boolean>(false);

  // Lock / Unlock confirm modal
  const [lockTarget, setLockTarget] = useState<AccountRow | null>(null);
  const [togglingLock, setTogglingLock] = useState<boolean>(false);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (search.trim()) qs.set('search', search.trim());
      if (roleFilter !== 'all') qs.set('role', roleFilter);
      const res = await apiFetch<{
        items: AccountRow[];
        can_manage_all_roles?: boolean;
        assignable_roles?: UserRole[];
      }>(`/accounts?${qs.toString()}`);
      setAccounts(res.items || []);
      setCanManageAllRoles(Boolean(res.can_manage_all_roles));
      if (res.assignable_roles && res.assignable_roles.length > 0) {
        setAssignableRoles(res.assignable_roles);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải danh sách tài khoản.');
    } finally {
      setLoading(false);
    }
  }, [search, roleFilter]);

  const loadAuditLogs = useCallback(async () => {
    setLoadingAudit(true);
    try {
      const res = await apiFetch<{ items: AuditLogRow[] }>('/audit/activity?limit=80');
      setAuditLogs(res.items || []);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể tải nhật ký hoạt động.', 'error');
    } finally {
      setLoadingAudit(false);
    }
  }, [showToast]);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadAccounts();
    }, 200);
    return () => clearTimeout(timer);
  }, [loadAccounts]);

  useEffect(() => {
    if (section === 'audit') {
      loadAuditLogs();
    }
  }, [section, loadAuditLogs]);

  const openCreateModal = async () => {
    setCreateOpen(true);
    try {
      const res = await apiFetch<{ items: EmployeeLite[] }>('/accounts/unlinked-employees');
      const available = res.items || [];
      setEmployees(available);
      if (available.length > 0) {
        const first = available[0];
        setCreateForm({
          employee_id: first.employee_id,
          username: `${first.employee_id.toLowerCase()}@company.vn`,
          password: '',
          role: (first.role as UserRole) || 'employee',
          must_change_password: true,
        });
      } else {
        setCreateForm({ employee_id: '', username: '', password: '', role: 'employee', must_change_password: true });
      }
    } catch {
      setEmployees([]);
    }
  };

  const handleCreateAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      await apiFetch('/accounts', {
        method: 'POST',
        body: JSON.stringify({
          employee_id: createForm.employee_id.trim().toUpperCase(),
          username: createForm.username.trim().toLowerCase(),
          password: createForm.password,
          role: createForm.role,
          must_change_password: createForm.must_change_password,
        }),
      });
      showToast(`Đã tạo tài khoản ${createForm.username} thành công.`, 'success');
      setCreateOpen(false);
      loadAccounts();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Tạo tài khoản thất bại.', 'error');
    } finally {
      setCreating(false);
    }
  };

  const openEditModal = (acc: AccountRow) => {
    setEditTarget(acc);
    setEditRole(acc.role);
    setResetPassword('');
    setForceChange(true);
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editTarget) return;
    setSavingEdit(true);
    try {
      const body: Record<string, unknown> = { role: editRole };
      if (resetPassword.trim()) {
        body.reset_password = resetPassword.trim();
        body.must_change_password = forceChange;
      }
      await apiFetch(`/accounts/${editTarget.user_id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      showToast(`Đã cập nhật tài khoản ${editTarget.username}.`, 'success');
      setEditTarget(null);
      loadAccounts();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể cập nhật tài khoản.', 'error');
    } finally {
      setSavingEdit(false);
    }
  };

  const handleConfirmToggleLock = async () => {
    if (!lockTarget) return;
    const nextActive = lockTarget.is_active !== 1;
    setTogglingLock(true);
    try {
      await apiFetch(`/accounts/${lockTarget.user_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: nextActive }),
      });
      showToast(
        nextActive
          ? `Đã mở khóa tài khoản ${lockTarget.username}.`
          : `Đã khóa tài khoản ${lockTarget.username}.`,
        'success'
      );
      setLockTarget(null);
      loadAccounts();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Thao tác khóa/mở khóa thất bại.', 'error');
    } finally {
      setTogglingLock(false);
    }
  };

  const accountColumns: ColumnDef<AccountRow>[] = [
    {
      key: 'username',
      header: 'Tên đăng nhập',
      render: (r) => (
        <div>
          <p className="font-mono font-semibold text-slate-900">{r.username}</p>
          <p className="text-[11px] text-slate-500">{r.user_id}</p>
        </div>
      ),
    },
    {
      key: 'full_name',
      header: 'Nhân viên liên kết',
      render: (r) => (
        <div>
          <p className="font-medium text-slate-900">{r.full_name}</p>
          <p className="text-[11px] text-slate-500">
            {r.employee_id} • {r.department_name}
          </p>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Vai trò',
      render: (r) => (
        <StatusBadge
          label={ROLE_LABELS[r.role] || r.role}
          variant={
            r.role === 'admin'
              ? 'high'
              : r.role === 'executive'
                ? 'medium'
                : r.role === 'hr'
                  ? 'approved'
                  : r.role === 'manager'
                    ? 'info'
                    : 'dismissed'
          }
        />
      ),
    },
    {
      key: 'is_active',
      header: 'Trạng thái',
      render: (r) => (
        <StatusBadge
          label={r.is_active === 1 ? 'Đang hoạt động' : 'Đã khóa'}
          variant={r.is_active === 1 ? 'approved' : 'rejected'}
        />
      ),
    },
    {
      key: 'last_login_at',
      header: 'Đăng nhập gần nhất',
      render: (r) => r.last_login_at || 'Chưa đăng nhập',
    },
    {
      key: 'actions',
      header: 'Thao tác',
      render: (r) => (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => openEditModal(r)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-brand-border bg-white text-[11px] font-medium text-slate-700 hover:bg-slate-50"
          >
            <KeyRound className="w-3 h-3" /> Phân quyền / MK
          </button>
          <button
            type="button"
            onClick={() => setLockTarget(r)}
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md border text-[11px] font-medium ${
              r.is_active === 1
                ? 'border-red-200 bg-red-50 text-brand-red hover:bg-red-100'
                : 'border-emerald-200 bg-emerald-50 text-brand-green hover:bg-emerald-100'
            }`}
          >
            {r.is_active === 1 ? (
              <>
                <Lock className="w-3 h-3" /> Khóa
              </>
            ) : (
              <>
                <Unlock className="w-3 h-3" /> Mở khóa
              </>
            )}
          </button>
        </div>
      ),
    },
  ];

  const auditColumns: ColumnDef<AuditLogRow>[] = [
    { key: 'created_at', header: 'Thời gian' },
    { key: 'actor_username', header: 'Người thực hiện', render: (r) => r.actor_username || r.actor_user_id },
    { key: 'action', header: 'Hành động', render: (r) => <StatusBadge label={r.action} variant="info" /> },
    { key: 'entity_type', header: 'Loại đối tượng' },
    { key: 'entity_id', header: 'Mã đối tượng', render: (r) => <span className="font-mono text-[11px]">{r.entity_id}</span> },
    {
      key: 'detail',
      header: 'Chi tiết thay đổi',
      render: (r) => (
        <button
          type="button"
          onClick={() => setSelectedAudit(r)}
          className="text-brand-blue hover:underline font-medium"
        >
          Xem JSON
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      {/* Header & Section Switcher */}
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/10 text-brand-navy flex items-center justify-center">
            <UserCog className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-900">Quản lý tài khoản & Bảo mật RBAC</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Cấp tài khoản đăng nhập, phân quyền vai trò, khóa/mở khóa (bảo vệ tài khoản Admin & HR cuối cùng) và tra cứu nhật ký audit.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSection('accounts')}
            className={`px-3.5 py-2 rounded-lg text-xs font-semibold transition-colors ${
              section === 'accounts' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            Tài khoản ({accounts.length})
          </button>
          <button
            type="button"
            onClick={() => setSection('audit')}
            className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold transition-colors ${
              section === 'audit' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            Nhật ký hoạt động
          </button>
          {section === 'accounts' && (
            <button
              type="button"
              onClick={openCreateModal}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700"
            >
              <Plus className="w-4 h-4" />
              Tạo tài khoản
            </button>
          )}
        </div>
      </div>

      {/* Security note */}
      <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-2.5 flex items-center gap-2.5 text-xs text-amber-900">
        <ShieldAlert className="w-4 h-4 text-brand-amber shrink-0" />
        <span>
          Quy tắc an toàn hệ thống: Backend tự động chặn mọi yêu cầu khóa/hạ quyền tài khoản <strong>Admin cuối cùng</strong> hoặc <strong>HR cuối cùng</strong> còn hoạt động, và tách bạch quyền kỹ thuật khỏi nghiệp vụ HR.
        </span>
      </div>

      {section === 'accounts' ? (
        <>
          <FilterBar
            searchPlaceholder="Tìm theo username, mã NV hoặc họ tên..."
            searchValue={search}
            onSearchChange={setSearch}
            selectLabel="Vai trò"
            selectValue={roleFilter}
            onSelectChange={setRoleFilter}
            selectOptions={[
              { value: 'all', label: 'Tất cả vai trò' },
              ...(canManageAllRoles
                ? [
                    { value: 'admin', label: 'Quản trị hệ thống (Admin)' },
                    { value: 'executive', label: 'Cấp lãnh đạo (Executive)' },
                  ]
                : []),
              { value: 'hr', label: 'Nhân sự (HR)' },
              { value: 'manager', label: 'Trưởng phòng' },
              { value: 'employee', label: 'Nhân viên' },
            ]}
          />

          {loading && <LoadingSkeleton rows={5} />}
          {!loading && error && <ErrorState message={error} onRetry={loadAccounts} />}
          {!loading && !error && (
            <DataTable
              columns={accountColumns}
              data={accounts}
              rowKey={(r) => r.user_id}
              emptyTitle="Không tìm thấy tài khoản phù hợp"
            />
          )}
        </>
      ) : (
        <>
          {loadingAudit ? (
            <LoadingSkeleton rows={5} />
          ) : (
            <DataTable
              columns={auditColumns}
              data={auditLogs}
              rowKey={(r) => String(r.id)}
              emptyTitle="Chưa có nhật ký hoạt động nào"
            />
          )}
        </>
      )}

      {/* Create Account Modal */}
      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-card border border-brand-border bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-brand-border">
              <h3 className="text-base font-bold text-slate-900">Tạo tài khoản đăng nhập mới</h3>
              <button type="button" onClick={() => setCreateOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleCreateAccount} className="mt-4 space-y-3.5 text-xs">
              <div>
                <label className="block font-medium text-slate-700 mb-1">Nhân viên liên kết *</label>
                {employees.length > 0 ? (
                  <select
                    required
                    value={createForm.employee_id}
                    onChange={(e) => {
                      const empId = e.target.value;
                      const picked = employees.find((item) => item.employee_id === empId);
                      const pickedRole = (picked?.role as UserRole) || 'employee';
                      setCreateForm({
                        ...createForm,
                        employee_id: empId,
                        username: `${empId.toLowerCase()}@company.vn`,
                        role: assignableRoles.includes(pickedRole) ? pickedRole : assignableRoles[0] || 'employee',
                      });
                    }}
                    className="w-full px-3 py-2 rounded-lg border border-brand-border bg-white"
                  >
                    {employees.map((e) => (
                      <option key={e.employee_id} value={e.employee_id}>
                        {e.employee_id} – {e.full_name} ({e.department_name})
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    required
                    value={createForm.employee_id}
                    onChange={(e) => setCreateForm({ ...createForm, employee_id: e.target.value })}
                    placeholder="Nhập mã NV chưa có tài khoản (VD: NV081)"
                    className="w-full px-3 py-2 rounded-lg border border-brand-border"
                  />
                )}
              </div>

              <div>
                <label className="block font-medium text-slate-700 mb-1">Tên đăng nhập (Email/Username) *</label>
                <input
                  type="text"
                  required
                  value={createForm.username}
                  onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                  placeholder="nv081@company.vn"
                  className="w-full px-3 py-2 rounded-lg border border-brand-border"
                />
              </div>

              <div>
                <label className="block font-medium text-slate-700 mb-1">Vai trò truy cập (RBAC) *</label>
                <select
                  value={createForm.role}
                  onChange={(e) => setCreateForm({ ...createForm, role: e.target.value as UserRole })}
                  className="w-full px-3 py-2 rounded-lg border border-brand-border bg-white"
                >
                  {assignableRoles.map((rCode) => (
                    <option key={rCode} value={rCode}>
                      {ROLE_LABELS[rCode] || rCode} ({rCode})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block font-medium text-slate-700 mb-1">Mật khẩu tạm thời (≥ 6 ký tự) *</label>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={createForm.password}
                  onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                  placeholder="Nhập mật khẩu khởi tạo"
                  className="w-full px-3 py-2 rounded-lg border border-brand-border"
                />
              </div>

              <label className="flex items-center gap-2 text-slate-700">
                <input
                  type="checkbox"
                  checked={createForm.must_change_password}
                  onChange={(e) => setCreateForm({ ...createForm, must_change_password: e.target.checked })}
                />
                <span>Yêu cầu đổi mật khẩu ở lần đăng nhập đầu tiên</span>
              </label>

              <div className="pt-3 flex justify-end gap-2 border-t border-brand-border">
                <button
                  type="button"
                  onClick={() => setCreateOpen(false)}
                  className="px-4 py-2 rounded-lg border border-brand-border text-slate-700"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 rounded-lg bg-brand-blue text-white font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {creating ? 'Đang tạo...' : 'Tạo tài khoản'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Role / Reset Password Modal */}
      {editTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-card border border-brand-border bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-brand-border">
              <h3 className="text-base font-bold text-slate-900">Phân quyền & Đặt lại mật khẩu</h3>
              <button type="button" onClick={() => setEditTarget(null)} className="text-slate-400 hover:text-slate-700">
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="mt-2 text-xs text-slate-600">
              Tài khoản: <strong className="font-mono text-slate-900">{editTarget.username}</strong> ({editTarget.full_name})
            </p>
            <form onSubmit={handleSaveEdit} className="mt-4 space-y-3.5 text-xs">
              <div>
                <label className="block font-medium text-slate-700 mb-1">Vai trò truy cập (RBAC)</label>
                <select
                  value={editRole}
                  onChange={(e) => setEditRole(e.target.value as UserRole)}
                  className="w-full px-3 py-2 rounded-lg border border-brand-border bg-white"
                >
                  {assignableRoles.map((rCode) => (
                    <option key={rCode} value={rCode}>
                      {ROLE_LABELS[rCode] || rCode} ({rCode})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block font-medium text-slate-700 mb-1">Đặt lại mật khẩu mới (bỏ trống nếu không đổi)</label>
                <input
                  type="password"
                  minLength={6}
                  value={resetPassword}
                  onChange={(e) => setResetPassword(e.target.value)}
                  placeholder="Nhập mật khẩu mới ≥ 6 ký tự"
                  className="w-full px-3 py-2 rounded-lg border border-brand-border"
                />
              </div>

              {resetPassword.trim().length > 0 && (
                <label className="flex items-center gap-2 text-slate-700">
                  <input
                    type="checkbox"
                    checked={forceChange}
                    onChange={(e) => setForceChange(e.target.checked)}
                  />
                  <span>Yêu cầu người dùng đổi lại mật khẩu sau khi đăng nhập</span>
                </label>
              )}

              <div className="pt-3 flex justify-end gap-2 border-t border-brand-border">
                <button
                  type="button"
                  onClick={() => setEditTarget(null)}
                  className="px-4 py-2 rounded-lg border border-brand-border text-slate-700"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={savingEdit}
                  className="px-4 py-2 rounded-lg bg-brand-navy text-white font-semibold hover:bg-slate-800 disabled:opacity-50"
                >
                  {savingEdit ? 'Đang lưu...' : 'Lưu cập nhật'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Audit Detail JSON Modal */}
      {selectedAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-lg rounded-card border border-brand-border bg-white p-6 shadow-xl space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-brand-border">
              <h3 className="text-sm font-bold text-slate-900">Chi tiết nhật ký #{selectedAudit.id} ({selectedAudit.action})</h3>
              <button type="button" onClick={() => setSelectedAudit(null)} className="text-slate-400 hover:text-slate-700">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="text-xs space-y-2">
              <p>
                <strong>Người thực hiện:</strong> {selectedAudit.actor_username || selectedAudit.actor_user_id} •{' '}
                <strong>Thời gian:</strong> {selectedAudit.created_at}
              </p>
              <div>
                <p className="font-semibold text-slate-700 mb-1">Trước thay đổi (before_json):</p>
                <pre className="p-2.5 rounded-lg bg-slate-50 border border-brand-border overflow-x-auto text-[11px]">
                  {selectedAudit.before_json || 'null'}
                </pre>
              </div>
              <div>
                <p className="font-semibold text-slate-700 mb-1">Sau thay đổi (after_json):</p>
                <pre className="p-2.5 rounded-lg bg-slate-50 border border-brand-border overflow-x-auto text-[11px]">
                  {selectedAudit.after_json || 'null'}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Lock / Unlock Confirm Modal */}
      <ConfirmModal
        isOpen={Boolean(lockTarget)}
        title={
          lockTarget?.is_active === 1
            ? `Khóa tài khoản ${lockTarget.username}?`
            : `Mở khóa tài khoản ${lockTarget?.username}?`
        }
        description={
          lockTarget?.is_active === 1
            ? `Tài khoản ${lockTarget.username} sẽ lập tức không thể đăng nhập hoặc gọi API cho đến khi được Quản trị viên mở khóa. Hệ thống sẽ từ chối nếu đây là tài khoản Admin hoặc HR hoạt động cuối cùng.`
            : `Khôi phục quyền đăng nhập cho tài khoản ${lockTarget?.username}.`
        }
        confirmLabel={lockTarget?.is_active === 1 ? 'Xác nhận khóa' : 'Xác nhận mở khóa'}
        isDanger={lockTarget?.is_active === 1}
        isLoading={togglingLock}
        onConfirm={handleConfirmToggleLock}
        onCancel={() => setLockTarget(null)}
      />
    </div>
  );
};
