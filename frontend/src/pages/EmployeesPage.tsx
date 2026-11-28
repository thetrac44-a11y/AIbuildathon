import React, { useCallback, useEffect, useState } from 'react';
import { Eye, Pencil, Plus, Power, UserPlus, Users, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { FilterBar } from '../components/ui/FilterBar';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface DepartmentItem {
  department_id: string;
  name: string;
}

interface EmployeeRow {
  employee_id: string;
  full_name: string;
  department_id: string;
  department_name: string;
  position: string;
  manager_id: string | null;
  manager_name: string | null;
  start_date: string;
  annual_leave_balance: number;
  used_annual_leave: number;
  remaining_annual_leave: number;
  role: 'employee' | 'manager' | 'hr';
  employment_status: 'active' | 'inactive' | 'terminated';
  email: string | null;
  phone: string | null;
}

interface EmployeeFormState {
  employee_id: string;
  full_name: string;
  department_id: string;
  position: string;
  manager_id: string;
  start_date: string;
  annual_leave_balance: number;
  role: 'employee' | 'manager' | 'hr';
  email: string;
  phone: string;
}

const INITIAL_FORM: EmployeeFormState = {
  employee_id: '',
  full_name: '',
  department_id: 'DEPT_TECH',
  position: '',
  manager_id: '',
  start_date: '2026-11-01',
  annual_leave_balance: 12,
  role: 'employee',
  email: '',
  phone: '',
};

const ROLE_LABEL: Record<string, string> = {
  employee: 'Nhân viên',
  manager: 'Trưởng phòng',
  hr: 'HR',
  executive: 'Cấp lãnh đạo',
  admin: 'Quản trị hệ thống',
};

export const EmployeesPage: React.FC = () => {
  const { user, showToast } = useAuth();
  const isHr = user?.role === 'hr';

  const [departments, setDepartments] = useState<DepartmentItem[]>([]);
  const [items, setItems] = useState<EmployeeRow[]>([]);
  const [canEdit, setCanEdit] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState<string>('');
  const [deptFilter, setDeptFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // Create / Edit Modal
  const [modalOpen, setModalOpen] = useState<boolean>(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<EmployeeFormState>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Deactivate / Reactivate Confirm Modal
  const [toggleTarget, setToggleTarget] = useState<EmployeeRow | null>(null);
  const [toggling, setToggling] = useState<boolean>(false);

  useEffect(() => {
    apiFetch<{ items: DepartmentItem[] }>('/departments')
      .then((res) => setDepartments(res.items || []))
      .catch(() => {
        // ignore
      });
  }, []);

  const loadEmployees = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (search.trim()) qs.set('search', search.trim());
      if (isHr && deptFilter) qs.set('department_id', deptFilter);
      if (statusFilter !== 'all') qs.set('employment_status', statusFilter);

      const res = await apiFetch<{ total: number; can_edit: boolean; items: EmployeeRow[] }>(
        `/employees?${qs.toString()}`
      );
      setItems(res.items || []);
      setCanEdit(Boolean(res.can_edit));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải danh sách nhân viên.');
    } finally {
      setLoading(false);
    }
  }, [search, isHr, deptFilter, statusFilter]);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadEmployees();
    }, 200);
    return () => clearTimeout(timer);
  }, [loadEmployees]);

  const openCreateModal = () => {
    setEditingId(null);
    setForm({
      ...INITIAL_FORM,
      department_id: departments[0]?.department_id || 'DEPT_TECH',
    });
    setModalOpen(true);
  };

  const openEditModal = (emp: EmployeeRow) => {
    setEditingId(emp.employee_id);
    setForm({
      employee_id: emp.employee_id,
      full_name: emp.full_name,
      department_id: emp.department_id,
      position: emp.position,
      manager_id: emp.manager_id || '',
      start_date: emp.start_date,
      annual_leave_balance: emp.annual_leave_balance,
      role: emp.role,
      email: emp.email || '',
      phone: emp.phone || '',
    });
    setModalOpen(true);
  };

  const handleSaveEmployee = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (editingId) {
        await apiFetch(`/employees/${editingId}`, {
          method: 'PATCH',
          body: JSON.stringify({
            full_name: form.full_name.trim(),
            department_id: form.department_id,
            position: form.position.trim(),
            manager_id: form.manager_id.trim() || null,
            annual_leave_balance: Number(form.annual_leave_balance),
            role: form.role,
            email: form.email.trim() || null,
            phone: form.phone.trim() || null,
          }),
        });
        showToast(`Đã cập nhật hồ sơ nhân viên ${editingId}.`, 'success');
      } else {
        await apiFetch('/employees', {
          method: 'POST',
          body: JSON.stringify({
            employee_id: form.employee_id.trim().toUpperCase(),
            full_name: form.full_name.trim(),
            department_id: form.department_id,
            position: form.position.trim(),
            manager_id: form.manager_id.trim() || null,
            start_date: form.start_date,
            annual_leave_balance: Number(form.annual_leave_balance),
            role: form.role,
            email: form.email.trim() || null,
            phone: form.phone.trim() || null,
          }),
        });
        showToast(`Đã thêm nhân viên mới ${form.employee_id.toUpperCase()}.`, 'success');
      }
      setModalOpen(false);
      loadEmployees();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Lưu thông tin nhân viên thất bại.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirmToggleStatus = async () => {
    if (!toggleTarget) return;
    const nextStatus = toggleTarget.employment_status === 'active' ? 'inactive' : 'active';
    setToggling(true);
    try {
      await apiFetch(`/employees/${toggleTarget.employee_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ employment_status: nextStatus }),
      });
      showToast(
        nextStatus === 'inactive'
          ? `Đã chuyển nhân viên ${toggleTarget.employee_id} sang trạng thái ngừng hoạt động (không xóa dữ liệu lịch sử).`
          : `Đã kích hoạt lại nhân viên ${toggleTarget.employee_id}.`,
        'success'
      );
      setToggleTarget(null);
      loadEmployees();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể thay đổi trạng thái nhân viên.', 'error');
    } finally {
      setToggling(false);
    }
  };

  const columns: ColumnDef<EmployeeRow>[] = [
    {
      key: 'employee_id',
      header: 'Mã NV',
      render: (r) => <span className="font-mono font-semibold text-brand-navy">{r.employee_id}</span>,
    },
    {
      key: 'full_name',
      header: 'Họ và tên',
      render: (r) => (
        <div>
          <p className="font-semibold text-slate-900">{r.full_name}</p>
          <p className="text-[11px] text-slate-500">{r.email || '—'}</p>
        </div>
      ),
    },
    { key: 'department_name', header: 'Phòng ban' },
    { key: 'position', header: 'Chức vụ' },
    {
      key: 'role',
      header: 'Vai trò',
      render: (r) => (
        <StatusBadge
          label={ROLE_LABEL[r.role] || r.role}
          variant={r.role === 'hr' ? 'high' : r.role === 'manager' ? 'info' : 'dismissed'}
        />
      ),
    },
    {
      key: 'remaining_annual_leave',
      header: 'Phép còn / Định mức',
      render: (r) => (
        <span>
          <strong className="text-brand-teal">{r.remaining_annual_leave}</strong> / {r.annual_leave_balance} ngày
        </span>
      ),
    },
    {
      key: 'employment_status',
      header: 'Trạng thái',
      render: (r) => (
        <StatusBadge
          label={r.employment_status === 'active' ? 'Đang làm việc' : 'Ngừng hoạt động'}
          variant={r.employment_status === 'active' ? 'approved' : 'dismissed'}
        />
      ),
    },
  ];

  if (canEdit) {
    columns.push({
      key: 'actions',
      header: 'Thao tác',
      render: (r) => (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              openEditModal(r);
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-brand-border bg-white text-[11px] font-medium text-slate-700 hover:bg-slate-50"
          >
            <Pencil className="w-3 h-3" /> Sửa
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setToggleTarget(r);
            }}
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md border text-[11px] font-medium ${
              r.employment_status === 'active'
                ? 'border-red-200 bg-red-50 text-brand-red hover:bg-red-100'
                : 'border-emerald-200 bg-emerald-50 text-brand-green hover:bg-emerald-100'
            }`}
          >
            <Power className="w-3 h-3" />
            {r.employment_status === 'active' ? 'Ngừng HĐ' : 'Kích hoạt'}
          </button>
        </div>
      ),
    });
  }

  return (
    <div className="space-y-5">
      {/* Header banner */}
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-600/10 text-brand-blue flex items-center justify-center">
            <Users className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">Quản lý hồ sơ nhân viên</h2>
              {!canEdit && (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
                  <Eye className="w-3 h-3" /> Chế độ chỉ xem (Phòng ban của bạn)
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              {canEdit
                ? 'HR có quyền thêm mới, chỉnh sửa thông tin và ngừng hoạt động nhân sự (bảo toàn lịch sử chấm công, không xóa cứng).'
                : 'Trưởng phòng có quyền tra cứu thông tin và quỹ phép năm của các thành viên trong phòng ban phụ trách.'}
            </p>
          </div>
        </div>

        {canEdit && (
          <button
            type="button"
            onClick={openCreateModal}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700"
          >
            <Plus className="w-4 h-4" />
            Thêm nhân viên
          </button>
        )}
      </div>

      {/* Filters */}
      <FilterBar
        searchPlaceholder="Tìm theo mã NV, họ tên hoặc chức vụ..."
        searchValue={search}
        onSearchChange={setSearch}
        selectLabel="Trạng thái"
        selectValue={statusFilter}
        onSelectChange={setStatusFilter}
        selectOptions={[
          { value: 'all', label: 'Tất cả trạng thái' },
          { value: 'active', label: 'Đang làm việc' },
          { value: 'inactive', label: 'Ngừng hoạt động' },
        ]}
        actions={
          isHr ? (
            <select
              aria-label="Lọc theo phòng ban"
              value={deptFilter}
              onChange={(e) => setDeptFilter(e.target.value)}
              className="px-3 py-2 text-xs rounded-lg border border-brand-border bg-brand-bg/60 text-slate-700"
            >
              <option value="">Tất cả phòng ban</option>
              {departments.map((d) => (
                <option key={d.department_id} value={d.department_id}>
                  Phòng {d.name}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />

      {loading && <LoadingSkeleton rows={5} />}
      {!loading && error && <ErrorState message={error} onRetry={loadEmployees} />}
      {!loading && !error && (
        <DataTable
          columns={columns}
          data={items}
          rowKey={(r) => r.employee_id}
          emptyTitle="Không tìm thấy nhân viên phù hợp"
        />
      )}

      {/* Create / Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-lg rounded-card border border-brand-border bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-brand-border">
              <div className="flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-brand-blue" />
                <h3 className="text-base font-bold text-slate-900">
                  {editingId ? `Cập nhật nhân viên ${editingId}` : 'Thêm hồ sơ nhân viên mới'}
                </h3>
              </div>
              <button type="button" onClick={() => setModalOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveEmployee} className="mt-4 space-y-3.5 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Mã nhân viên *</label>
                  <input
                    type="text"
                    required
                    disabled={Boolean(editingId)}
                    value={form.employee_id}
                    onChange={(e) => setForm({ ...form, employee_id: e.target.value })}
                    placeholder="VD: NV081"
                    className="w-full px-3 py-2 rounded-lg border border-brand-border disabled:bg-slate-100"
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Họ và tên *</label>
                  <input
                    type="text"
                    required
                    value={form.full_name}
                    onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                    placeholder="Nguyễn Văn A"
                    className="w-full px-3 py-2 rounded-lg border border-brand-border"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Phòng ban *</label>
                  <select
                    value={form.department_id}
                    onChange={(e) => setForm({ ...form, department_id: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg border border-brand-border bg-white"
                  >
                    {departments.map((d) => (
                      <option key={d.department_id} value={d.department_id}>
                        {d.name} ({d.department_id})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Chức vụ *</label>
                  <input
                    type="text"
                    required
                    value={form.position}
                    onChange={(e) => setForm({ ...form, position: e.target.value })}
                    placeholder="Chuyên viên Kinh doanh"
                    className="w-full px-3 py-2 rounded-lg border border-brand-border"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Vai trò hệ thống *</label>
                  <select
                    value={form.role}
                    onChange={(e) => setForm({ ...form, role: e.target.value as 'employee' | 'manager' | 'hr' })}
                    className="w-full px-3 py-2 rounded-lg border border-brand-border bg-white"
                  >
                    <option value="employee">Nhân viên</option>
                    <option value="manager">Trưởng phòng</option>
                    <option value="hr">Nhân sự (HR)</option>
                  </select>
                </div>
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Phép năm (ngày)</label>
                  <input
                    type="number"
                    min={0}
                    max={60}
                    step={0.5}
                    value={form.annual_leave_balance}
                    onChange={(e) => setForm({ ...form, annual_leave_balance: Number(e.target.value) })}
                    className="w-full px-3 py-2 rounded-lg border border-brand-border"
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Ngày vào làm *</label>
                  <input
                    type="date"
                    required
                    disabled={Boolean(editingId)}
                    value={form.start_date}
                    onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg border border-brand-border disabled:bg-slate-100"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Mã quản lý trực tiếp</label>
                  <input
                    type="text"
                    value={form.manager_id}
                    onChange={(e) => setForm({ ...form, manager_id: e.target.value })}
                    placeholder="VD: NV001"
                    className="w-full px-3 py-2 rounded-lg border border-brand-border"
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Email</label>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    placeholder="nv081@company.vn"
                    className="w-full px-3 py-2 rounded-lg border border-brand-border"
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-700 mb-1">Số điện thoại</label>
                  <input
                    type="text"
                    value={form.phone}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })}
                    placeholder="0901..."
                    className="w-full px-3 py-2 rounded-lg border border-brand-border"
                  />
                </div>
              </div>

              <div className="pt-3 flex items-center justify-end gap-2.5 border-t border-brand-border">
                <button
                  type="button"
                  onClick={() => setModalOpen(false)}
                  className="px-4 py-2 rounded-lg border border-brand-border font-medium text-slate-700 hover:bg-slate-50"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 rounded-lg bg-brand-blue text-white font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {submitting ? 'Đang lưu...' : editingId ? 'Lưu thay đổi' : 'Tạo nhân viên'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Deactivate / Reactivate Confirm Modal */}
      <ConfirmModal
        isOpen={Boolean(toggleTarget)}
        title={
          toggleTarget?.employment_status === 'active'
            ? `Ngừng hoạt động nhân viên ${toggleTarget.employee_id}?`
            : `Kích hoạt lại nhân viên ${toggleTarget?.employee_id}?`
        }
        description={
          toggleTarget?.employment_status === 'active'
            ? `Nhân viên ${toggleTarget.full_name} sẽ được chuyển sang trạng thái ngừng hoạt động (soft-deactivate). Dữ liệu chấm công, đơn nghỉ và báo cáo lịch sử vẫn được bảo toàn.`
            : `Nhân viên ${toggleTarget?.full_name} sẽ được khôi phục trạng thái đang làm việc.`
        }
        confirmLabel={toggleTarget?.employment_status === 'active' ? 'Xác nhận ngừng hoạt động' : 'Kích hoạt lại'}
        isDanger={toggleTarget?.employment_status === 'active'}
        isLoading={toggling}
        onConfirm={handleConfirmToggleStatus}
        onCancel={() => setToggleTarget(null)}
      />
    </div>
  );
};
