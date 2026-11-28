import React, { useCallback, useEffect, useState } from 'react';
import { KeyRound, Save, ShieldAlert } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface RoleItem {
  role_id: number;
  role_code: string;
  role_name: string;
  description: string;
  active_users: number;
  permissions: string[];
}

interface PermissionItem {
  permission_id: number;
  permission_code: string;
  permission_name: string;
  description: string;
}

export const RbacManagementPage: React.FC = () => {
  const { showToast } = useAuth();
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [permissions, setPermissions] = useState<PermissionItem[]>([]);
  const [selectedRoleCode, setSelectedRoleCode] = useState<string>('admin');
  const [draftPerms, setDraftPerms] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rRes, pRes] = await Promise.all([
        apiFetch<{ items: RoleItem[] }>('/rbac/roles'),
        apiFetch<{ items: PermissionItem[] }>('/rbac/permissions'),
      ]);
      setRoles(rRes.items || []);
      setPermissions(pRes.items || []);
      const active = (rRes.items || []).find((r) => r.role_code === selectedRoleCode) ?? rRes.items?.[0];
      if (active) {
        setSelectedRoleCode(active.role_code);
        setDraftPerms(new Set(active.permissions));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải cấu hình phân quyền RBAC.');
    } finally {
      setLoading(false);
    }
  }, [selectedRoleCode]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSelectRole = (role: RoleItem) => {
    setSelectedRoleCode(role.role_code);
    setDraftPerms(new Set(role.permissions));
  };

  const togglePerm = (code: string) => {
    setDraftPerms((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiFetch(`/rbac/roles/${selectedRoleCode}/permissions`, {
        method: 'PATCH',
        body: JSON.stringify({ permissions: Array.from(draftPerms).sort() }),
      });
      showToast(`Đã cập nhật ${draftPerms.size} quyền cho vai trò ${selectedRoleCode.toUpperCase()}.`, 'success');
      loadData();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Lưu phân quyền thất bại.', 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading && roles.length === 0) return <LoadingSkeleton rows={5} />;
  if (error) return <ErrorState message={error} onRetry={loadData} />;

  const activeRole = roles.find((r) => r.role_code === selectedRoleCode);

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/10 text-brand-navy flex items-center justify-center">
            <KeyRound className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-900">Quản lý Vai trò &amp; Ma trận Phân quyền RBAC</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Cấu hình quyền chi tiết cho 5 vai trò doanh nghiệp. Thay đổi được kiểm tra bảo mật ở Backend và áp dụng ngay lập tức.
            </p>
          </div>
        </div>
        <button
          type="button"
          disabled={saving || !activeRole}
          onClick={handleSave}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {saving ? 'Đang lưu...' : 'Lưu ma trận quyền'}
        </button>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-4 py-2.5 flex items-center gap-2.5 text-xs text-amber-900">
        <ShieldAlert className="w-4 h-4 text-brand-amber shrink-0" />
        <span>
          Nguyên tắc bảo vệ: Không thể gỡ các quyền quản trị cốt lõi (<code>role.manage</code>, <code>account.manage</code>, <code>system.dashboard</code>) khỏi vai trò <strong>admin</strong> để chống tự khóa hệ thống.
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        <div className="space-y-2">
          {roles.map((r) => {
            const selected = r.role_code === selectedRoleCode;
            return (
              <button
                key={r.role_code}
                type="button"
                onClick={() => handleSelectRole(r)}
                className={`w-full text-left rounded-card border p-3.5 transition-all ${
                  selected
                    ? 'border-brand-blue bg-blue-50/60 shadow-sm'
                    : 'border-brand-border bg-white hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-900">{r.role_name}</span>
                  <StatusBadge label={`${r.active_users} user`} variant={selected ? 'info' : 'dismissed'} />
                </div>
                <p className="text-[11px] font-mono text-brand-blue mt-0.5">{r.role_code}</p>
                <p className="text-[11px] text-slate-500 mt-1 line-clamp-2">{r.description}</p>
              </button>
            );
          })}
        </div>

        <div className="lg:col-span-3 rounded-card border border-brand-border bg-white p-5 shadow-sm">
          {activeRole && (
            <>
              <div className="flex items-center justify-between pb-3 mb-4 border-b border-brand-border">
                <div>
                  <h3 className="text-sm font-bold text-slate-900">
                    Quyền hạn của vai trò: {activeRole.role_name} ({activeRole.role_code})
                  </h3>
                  <p className="text-xs text-slate-500">Đã bật {draftPerms.size} / {permissions.length} quyền</p>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[540px] overflow-y-auto pr-1">
                {permissions.map((p) => {
                  const checked = draftPerms.has(p.permission_code);
                  return (
                    <label
                      key={p.permission_code}
                      className={`flex items-start gap-2.5 p-3 rounded-xl border cursor-pointer transition-colors ${
                        checked ? 'border-blue-200 bg-blue-50/40' : 'border-brand-border bg-white hover:bg-slate-50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => togglePerm(p.permission_code)}
                        className="mt-0.5"
                      />
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-slate-900">{p.permission_name}</p>
                        <p className="text-[11px] font-mono text-brand-blue">{p.permission_code}</p>
                        <p className="text-[11px] text-slate-500 mt-0.5">{p.description}</p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
