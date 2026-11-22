import React, { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { FilterBar } from '../components/ui/FilterBar';
import { DataTable, ColumnDef } from '../components/ui/DataTable';
import { StatusBadge, BadgeVariant } from '../components/ui/StatusBadge';
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
  const { user, selectedPeriod } = useAuth();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [resp, setResp] = useState<AttendanceResponse | null>(null);
  const [selectedRow, setSelectedRow] = useState<AttendanceRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        <strong>5 phút</strong>. Đây là lịch sử dữ liệu ghi nhận (chỉ đọc).
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
          onRowClick={(r) => setSelectedRow(r)}
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
          </div>
        </div>
      )}
    </div>
  );
};
