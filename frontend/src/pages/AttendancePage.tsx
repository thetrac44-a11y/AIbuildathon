import React, { useCallback, useEffect, useState } from 'react';
import { Pencil, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { hasPermission } from '../config/navigation';
import { apiFetch, ApiError } from '../lib/api';
import { PermissionGuard } from '../components/layout/PermissionGuard';
import { FilterBar } from '../components/ui/FilterBar';
import { DataTable, ColumnDef } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface AttendanceRow {
  id: number;
  employee_id: string;
  full_name: string;
  department_id: string;
  department_name: string;
  work_date: string;
  check_in: string | null;
  check_out: string | null;
  work_hours: number;
  late_minutes: number;
  is_late: number;
  status: string;
  source: string;
}

interface AttendanceResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  items: AttendanceRow[];
}

function renderAttendanceBadge(row: AttendanceRow) {
  if (row.status === 'on_leave') return <StatusBadge label="Nghỉ phép" variant="info" />;
  if (row.status === 'holiday') return <StatusBadge label="Ngày lễ" variant="dismissed" />;
  if (row.status === 'absent') return <StatusBadge label="Vắng" variant="high" />;
  if (row.status === 'present' && (!row.check_in || !row.check_out)) {
    return <StatusBadge label="Thiếu chấm công" variant="medium" />;
  }
  if (row.is_late === 1) return <StatusBadge label={`Đi muộn (+${row.late_minutes}p)`} variant="pending" />;
  return <StatusBadge label="Đúng giờ" variant="approved" />;
}

export const AttendancePage: React.FC = () => {
  const { user, selectedPeriod, showToast } = useAuth();
  const canAdjustAttendance = hasPermission(user, 'attendance.adjust') && user?.role === 'hr';
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [resp, setResp] = useState<AttendanceResponse | null>(null);
  const [selectedRow, setSelectedRow] = useState<AttendanceRow | null>(null);
  const [adjCheckIn, setAdjCheckIn] = useState('');
  const [adjCheckOut, setAdjCheckOut] = useState('');
  const [adjStatus, setAdjStatus] = useState('present');
  const [adjReason, setAdjReason] = useState('');
  const [savingAdj, setSavingAdj] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const openDetailDrawer = (row: AttendanceRow) => {
    setSelectedRow(row);
    setAdjCheckIn(row.check_in ?? '');
    setAdjCheckOut(row.check_out ?? '');
    setAdjStatus(row.status);
    setAdjReason('');
  };

  const handleAdjustSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRow) return;
    if (adjReason.trim().length < 3) {
      showToast('Vui lòng nhập lý do điều chỉnh chấm công (tối thiểu 3 ký tự).', 'error');
      return;
    }
    setSavingAdj(true);
    try {
      const updated = await apiFetch<{ status: string; record: AttendanceRow }>(
        `/attendance/${selectedRow.id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            check_in: adjCheckIn.trim(),
            check_out: adjCheckOut.trim(),
            status: adjStatus,
            reason: adjReason.trim(),
          }),
        }
      );
      showToast(`Đã điều chỉnh ngày công ${selectedRow.work_date} (${selectedRow.employee_id}).`, 'success');
      setSelectedRow(updated.record);
      setAdjReason('');
      loadData();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Điều chỉnh chấm công thất bại.', 'error');
    } finally {
      setSavingAdj(false);
    }
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        period: selectedPeriod,
        status: statusFilter,
        page: String(page),
        page_size: '25',
      });
      if (search.trim()) qs.set('search', search.trim());
      const data = await apiFetch<AttendanceResponse>(`/attendance?${qs.toString()}`);
      setResp(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải dữ liệu chấm công.');
    } finally {
      setLoading(false);
    }
  }, [selectedPeriod, statusFilter, search, page]);

  useEffect(() => {
    setPage(1);
  }, [selectedPeriod, statusFilter, search]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const columns: ColumnDef<AttendanceRow>[] = [
    { key: 'employee_id', header: 'Mã NV' },
    ...(user?.role !== 'employee'
      ? [
          { key: 'full_name', header: 'Họ và tên' },
          { key: 'department_name', header: 'Phòng ban' },
        ]
      : []),
    { key: 'work_date', header: 'Ngày làm' },
    { key: 'check_in', header: 'Giờ vào', render: (r) => (r.check_in ? r.check_in.slice(11) : '—') },
    { key: 'check_out', header: 'Giờ ra', render: (r) => (r.check_out ? r.check_out.slice(11) : '—') },
    { key: 'work_hours', header: 'Giờ công', render: (r) => `${r.work_hours}h` },
    { key: 'status', header: 'Trạng thái', render: renderAttendanceBadge },
    { key: 'source', header: 'Nguồn' },
  ];

  return (
    <div className="space-y-4">
      <div className="text-xs text-slate-500">
        Quy chuẩn chấm công: <strong>08:30–17:30</strong>, nghỉ trưa 1 giờ (8h/ngày), ân hạn đi muộn{' '}
        <strong>5 phút</strong>.{' '}
        {canAdjustAttendance
          ? 'HR có thể nhấp vào dòng chấm công nhân viên khác để điều chỉnh nghiệp vụ có lý do và audit.'
          : 'Đây là lịch sử dữ liệu ghi nhận (chỉ đọc).'}
      </div>

      <FilterBar
        searchPlaceholder="Tìm mã NV hoặc họ tên..."
        searchValue={search}
        onSearchChange={user?.role !== 'employee' ? setSearch : undefined}
        selectLabel="Trạng thái"
        selectValue={statusFilter}
        onSelectChange={setStatusFilter}
        selectOptions={[
          { value: 'all', label: 'Tất cả trạng thái' },
          { value: 'on_time', label: 'Đúng giờ' },
          { value: 'late', label: 'Đi muộn (>5p)' },
          { value: 'missing_punch', label: 'Thiếu chấm công' },
          { value: 'on_leave', label: 'Nghỉ phép' },
          { value: 'absent', label: 'Vắng mặt' },
        ]}
      />

      {error && <ErrorState message={error} onRetry={loadData} />}
      {loading ? (
        <LoadingSkeleton rows={6} />
      ) : (
        <DataTable
          columns={columns}
          data={resp?.items ?? []}
          rowKey={(r) => String(r.id)}
          onRowClick={openDetailDrawer}
          pagination={
            resp
              ? {
                  page: resp.page,
                  pageSize: resp.page_size,
                  totalCount: resp.total,
                  onPageChange: setPage,
                }
              : undefined
          }
        />
      )}

      {/* Detail Drawer */}
      {selectedRow && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40">
          <div className="w-full max-w-md bg-white h-full shadow-2xl p-6 overflow-y-auto">
            <div className="flex items-center justify-between border-b border-brand-border pb-3">
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  Chi tiết ngày công {selectedRow.work_date}
                </h3>
                <p className="text-xs text-slate-500">
                  {selectedRow.employee_id} · {selectedRow.full_name}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedRow(null)}
                className="p-1.5 rounded-lg hover:bg-slate-100"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <dl className="mt-4 space-y-3 text-xs">
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Phòng ban</dt>
                <dd className="font-semibold">{selectedRow.department_name}</dd>
              </div>
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Giờ vào</dt>
                <dd className="font-mono">{selectedRow.check_in ?? 'Thiếu dữ liệu'}</dd>
              </div>
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Giờ ra</dt>
                <dd className="font-mono">{selectedRow.check_out ?? 'Thiếu dữ liệu'}</dd>
              </div>
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Giờ công tính được</dt>
                <dd className="font-bold text-brand-blue">{selectedRow.work_hours} giờ</dd>
              </div>
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Số phút đi muộn (&gt;5p)</dt>
                <dd className="font-semibold">{selectedRow.late_minutes} phút</dd>
              </div>
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Trạng thái</dt>
                <dd>{renderAttendanceBadge(selectedRow)}</dd>
              </div>
              <div className="flex justify-between py-1.5">
                <dt className="text-slate-500">Nguồn dữ liệu</dt>
                <dd className="font-medium">{selectedRow.source}</dd>
              </div>
            </dl>

            <PermissionGuard permission="attendance.adjust" roles={['hr']}>
              {selectedRow.employee_id !== user?.employee_id ? (
                <form
                  onSubmit={handleAdjustSubmit}
                  className="mt-6 pt-5 border-t border-brand-border space-y-3 text-xs"
                >
                  <div className="flex items-center gap-1.5 font-bold text-slate-900">
                    <Pencil className="w-3.5 h-3.5 text-brand-blue" />
                    <span>Điều chỉnh chấm công nghiệp vụ (HR)</span>
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Trạng thái</label>
                    <select
                      value={adjStatus}
                      onChange={(e) => setAdjStatus(e.target.value)}
                      className="w-full px-3 py-1.5 rounded-lg border border-brand-border bg-white"
                    >
                      <option value="present">Có mặt (present)</option>
                      <option value="absent">Vắng mặt (absent)</option>
                      <option value="on_leave">Nghỉ phép (on_leave)</option>
                      <option value="holiday">Ngày lễ (holiday)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Giờ vào (YYYY-MM-DD HH:MM:SS)</label>
                    <input
                      type="text"
                      value={adjCheckIn}
                      onChange={(e) => setAdjCheckIn(e.target.value)}
                      placeholder={`${selectedRow.work_date} 08:25:00`}
                      className="w-full px-3 py-1.5 rounded-lg border border-brand-border font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Giờ ra (YYYY-MM-DD HH:MM:SS)</label>
                    <input
                      type="text"
                      value={adjCheckOut}
                      onChange={(e) => setAdjCheckOut(e.target.value)}
                      placeholder={`${selectedRow.work_date} 17:30:00`}
                      className="w-full px-3 py-1.5 rounded-lg border border-brand-border font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-slate-600 mb-1">Lý do điều chỉnh (bắt buộc) *</label>
                    <textarea
                      required
                      minLength={3}
                      rows={2}
                      value={adjReason}
                      onChange={(e) => setAdjReason(e.target.value)}
                      placeholder="VD: Đối soát vân tay thực tế / lỗi đồng bộ máy chấm công"
                      className="w-full px-3 py-1.5 rounded-lg border border-brand-border"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={savingAdj}
                    className="w-full py-2 rounded-lg bg-brand-blue text-white font-semibold hover:bg-blue-700 disabled:opacity-50"
                  >
                    {savingAdj ? 'Đang lưu điều chỉnh...' : 'Lưu điều chỉnh công'}
                  </button>
                </form>
              ) : (
                <p className="mt-5 pt-4 border-t border-brand-border text-[11px] text-slate-500">
                  Không cho phép tự điều chỉnh bản ghi chấm công của chính mình.
                </p>
              )}
            </PermissionGuard>
          </div>
        </div>
      )}
    </div>
  );
};
