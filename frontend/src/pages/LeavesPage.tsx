import React, { useCallback, useEffect, useState } from 'react';
import { Plus, X, Check, Ban } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { hasPermission } from '../config/navigation';
import { apiFetch, ApiError } from '../lib/api';
import { KpiCard } from '../components/ui/KpiCard';
import { FilterBar } from '../components/ui/FilterBar';
import { DataTable, ColumnDef } from '../components/ui/DataTable';
import { StatusBadge, BadgeVariant } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';
import { ConfirmModal } from '../components/ui/ConfirmModal';

interface LeaveRow {
  request_id: number;
  employee_id: string;
  full_name: string;
  department_name: string;
  leave_type: string;
  from_date: string;
  to_date: string;
  leave_days: number;
  reason: string;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  requires_executive_approval?: boolean;
  reviewed_by: string | null;
  decision_note: string | null;
  created_at: string;
  can_review: boolean;
  can_cancel: boolean;
}

interface LeavesResponse {
  total: number;
  period?: string;
  kpis: { pending: number; pending_all?: number; approved: number; rejected: number };
  my_balance: {
    annual_leave_balance: number;
    used_annual_leave: number;
    remaining_annual_leave: number;
  };
  items: LeaveRow[];
}

interface LeaveTimelineItem {
  id: number;
  action: string;
  note: string | null;
  created_at: string;
  actor_username: string | null;
  actor_name: string | null;
}

const TIMELINE_ACTION_VN: Record<string, { label: string; variant: BadgeVariant }> = {
  submit: { label: 'Gửi đơn', variant: 'info' },
  approve: { label: 'Phê duyệt', variant: 'approved' },
  override: { label: 'HR duyệt', variant: 'approved' },
  reject: { label: 'Từ chối', variant: 'rejected' },
  cancel: { label: 'Tự hủy đơn', variant: 'dismissed' },
};

const LEAVE_TYPE_VN: Record<string, string> = {
  annual: 'Phép năm',
  sick: 'Nghỉ ốm',
  personal: 'Việc riêng',
  unpaid: 'Không lương',
};

const LEAVE_STATUS_VN: Record<string, { label: string; variant: BadgeVariant }> = {
  pending: { label: 'Chờ duyệt', variant: 'pending' },
  approved: { label: 'Đã duyệt', variant: 'approved' },
  rejected: { label: 'Từ chối', variant: 'rejected' },
  cancelled: { label: 'Đã hủy', variant: 'dismissed' },
};

export const LeavesPage: React.FC = () => {
  const { user, selectedPeriod, showToast } = useAuth();
  const canCreateLeave = hasPermission(user, 'leave.create.self');
  const isExecutiveApprover = hasPermission(user, 'leave.approve.executive');
  const [data, setData] = useState<LeavesResponse | null>(null);
  const [filterAllPeriods, setFilterAllPeriods] = useState(isExecutiveApprover);
  const [onlyExecutiveApproval, setOnlyExecutiveApproval] = useState(isExecutiveApprover);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form modal
  const [createOpen, setCreateOpen] = useState(false);
  const [leaveType, setLeaveType] = useState('annual');
  const [fromDate, setFromDate] = useState('2026-12-01');
  const [toDate, setToDate] = useState('2026-12-02');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Review / detail modal + approval timeline (BUG-10)
  const [selected, setSelected] = useState<LeaveRow | null>(null);
  const [timeline, setTimeline] = useState<LeaveTimelineItem[]>([]);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [decisionNote, setDecisionNote] = useState('');
  const [cancelTarget, setCancelTarget] = useState<LeaveRow | null>(null);

  const loadLeaves = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ status: statusFilter });
      if (!filterAllPeriods) qs.set('period', selectedPeriod);
      if (onlyExecutiveApproval) qs.set('requires_executive_approval', 'true');
      if (search.trim()) qs.set('search', search.trim());
      const res = await apiFetch<LeavesResponse>(`/leaves?${qs.toString()}`);
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải danh sách đơn nghỉ phép.');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, filterAllPeriods, onlyExecutiveApproval, selectedPeriod, search]);

  useEffect(() => {
    loadLeaves();
  }, [loadLeaves]);

  useEffect(() => {
    if (!selected) {
      setTimeline([]);
      return;
    }
    let cancelled = false;
    setLoadingTimeline(true);
    apiFetch<{ request: LeaveRow; timeline: LeaveTimelineItem[] }>(`/leaves/${selected.request_id}`)
      .then((res) => {
        if (!cancelled) setTimeline(res.timeline ?? []);
      })
      .catch(() => {
        if (!cancelled) setTimeline([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingTimeline(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await apiFetch('/leaves', {
        method: 'POST',
        body: JSON.stringify({ leave_type: leaveType, from_date: fromDate, to_date: toDate, reason }),
      });
      showToast('Đã gửi đơn nghỉ phép thành công (Trạng thái: Chờ duyệt).', 'success');
      setCreateOpen(false);
      setReason('');
      loadLeaves();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Gửi đơn thất bại.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReview = async (decision: 'approved' | 'rejected') => {
    if (!selected) return;
    if (decision === 'rejected' && !decisionNote.trim()) {
      showToast('Vui lòng nhập lý do bắt buộc khi từ chối đơn.', 'error');
      return;
    }
    setSubmitting(true);
    try {
      await apiFetch(`/leaves/${selected.request_id}/review`, {
        method: 'POST',
        body: JSON.stringify({ decision, decision_note: decisionNote }),
      });
      showToast(
        decision === 'approved' ? 'Đã phê duyệt đơn nghỉ phép.' : 'Đã từ chối đơn nghỉ phép.',
        'success'
      );
      setSelected(null);
      setDecisionNote('');
      loadLeaves();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể xử lý đơn.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (!cancelTarget) return;
    setSubmitting(true);
    try {
      await apiFetch(`/leaves/${cancelTarget.request_id}/cancel`, { method: 'POST' });
      showToast('Đã hủy đơn nghỉ phép chờ duyệt.', 'info');
      setCancelTarget(null);
      loadLeaves();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Hủy đơn thất bại.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnDef<LeaveRow>[] = [
    { key: 'request_id', header: 'Mã đơn', render: (r) => `#${r.request_id}` },
    { key: 'full_name', header: 'Nhân viên', render: (r) => `${r.employee_id} · ${r.full_name}` },
    { key: 'department_name', header: 'Phòng ban' },
    { key: 'leave_type', header: 'Loại nghỉ', render: (r) => LEAVE_TYPE_VN[r.leave_type] ?? r.leave_type },
    { key: 'date_range', header: 'Thời gian', render: (r) => `${r.from_date} → ${r.to_date}` },
    { key: 'leave_days', header: 'Số ngày', render: (r) => `${r.leave_days} ngày` },
    {
      key: 'status',
      header: 'Trạng thái',
      render: (r) => {
        const info = LEAVE_STATUS_VN[r.status] ?? { label: r.status, variant: 'info' as BadgeVariant };
        return (
          <div className="flex flex-wrap items-center gap-1">
            <StatusBadge label={info.label} variant={info.variant} />
            {r.requires_executive_approval && (
              <StatusBadge label="Cấp BGĐ" variant="high" />
            )}
          </div>
        );
      },
    },
    {
      key: 'actions',
      header: 'Thao tác',
      render: (r) => (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => {
              setSelected(r);
              setDecisionNote('');
            }}
            className="text-brand-blue font-semibold hover:underline"
          >
            {r.can_review ? 'Xem & Duyệt' : 'Chi tiết'}
          </button>
          {r.can_cancel && (
            <button
              type="button"
              onClick={() => setCancelTarget(r)}
              className="text-brand-red font-medium hover:underline"
            >
              Hủy
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <KpiCard
            title="Đơn chờ duyệt (hiện hành)"
            value={`${data.kpis.pending_all ?? data.kpis.pending} đơn`}
            subtitle={
              filterAllPeriods
                ? 'Đang xem tất cả kỳ'
                : `Trong kỳ ${selectedPeriod}: ${data.kpis.pending} đơn`
            }
            tooltip="Tổng đơn nghỉ phép đang chờ phê duyệt trong phạm vi quyền hạn; nhấp để lọc nhanh"
            tone="amber"
            onClick={() => {
              setFilterAllPeriods(true);
              setStatusFilter('pending');
            }}
          />
          <KpiCard
            title="Đơn đã duyệt"
            value={`${data.kpis.approved} đơn`}
            subtitle={filterAllPeriods ? 'Tất cả kỳ' : `Trong kỳ ${selectedPeriod}`}
            tone="green"
          />
          <KpiCard
            title="Đơn từ chối"
            value={`${data.kpis.rejected} đơn`}
            subtitle={filterAllPeriods ? 'Tất cả kỳ' : `Trong kỳ ${selectedPeriod}`}
            tone="red"
          />
          <KpiCard
            title="Phép năm còn lại của tôi"
            value={`${data.my_balance.remaining_annual_leave} ngày`}
            subtitle={`Đã duyệt: ${data.my_balance.used_annual_leave}/${data.my_balance.annual_leave_balance} ngày`}
            tone="blue"
          />
        </div>
      )}

      <FilterBar
        searchPlaceholder="Tìm nhân viên hoặc lý do..."
        searchValue={search}
        onSearchChange={user?.role !== 'employee' ? setSearch : undefined}
        selectLabel="Trạng thái"
        selectValue={statusFilter}
        onSelectChange={setStatusFilter}
        selectOptions={[
          { value: 'all', label: 'Tất cả' },
          { value: 'pending', label: 'Chờ duyệt' },
          { value: 'approved', label: 'Đã duyệt' },
          { value: 'rejected', label: 'Từ chối' },
          { value: 'cancelled', label: 'Đã hủy' },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2.5">
            {isExecutiveApprover && (
              <label className="inline-flex items-center gap-1.5 text-xs font-medium text-brand-navy cursor-pointer px-2">
                <input
                  type="checkbox"
                  checked={onlyExecutiveApproval}
                  onChange={(e) => setOnlyExecutiveApproval(e.target.checked)}
                />
                Chỉ đơn cần BGĐ duyệt
              </label>
            )}
            <label className="inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer px-2">
              <input
                type="checkbox"
                checked={filterAllPeriods}
                onChange={(e) => setFilterAllPeriods(e.target.checked)}
              />
              Tất cả kỳ
            </label>
            {canCreateLeave && (
              <button
                type="button"
                onClick={() => setCreateOpen(true)}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700"
              >
                <Plus className="w-4 h-4" /> Tạo đơn nghỉ phép
              </button>
            )}
          </div>
        }
      />

      {error && <ErrorState message={error} onRetry={loadLeaves} />}
      {loading ? (
        <LoadingSkeleton rows={5} />
      ) : (
        <DataTable columns={columns} data={data?.items ?? []} rowKey={(r) => String(r.request_id)} />
      )}

      {/* Create Leave Modal */}
      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <form
            onSubmit={handleCreate}
            className="w-full max-w-md rounded-card border border-brand-border bg-white p-6 shadow-xl space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900">Tạo đơn xin nghỉ phép mới</h3>
              <button type="button" onClick={() => setCreateOpen(false)}>
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Loại nghỉ</label>
              <select
                value={leaveType}
                onChange={(e) => setLeaveType(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border"
              >
                <option value="annual">Phép năm</option>
                <option value="sick">Nghỉ ốm</option>
                <option value="personal">Việc riêng</option>
                <option value="unpaid">Nghỉ không lương</option>
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Từ ngày</label>
                <input
                  type="date"
                  required
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Đến ngày</label>
                <input
                  type="date"
                  required
                  value={toDate}
                  onChange={(e) => setToDate(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Lý do nghỉ</label>
              <textarea
                required
                minLength={3}
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Nhập lý do xin nghỉ..."
                className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="px-4 py-2 rounded-lg border border-brand-border text-xs font-medium"
              >
                Hủy
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold disabled:opacity-50"
              >
                {submitting ? 'Đang gửi...' : 'Gửi đơn'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Detail & Review Modal */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-lg rounded-card border border-brand-border bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-brand-border pb-3">
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  Chi tiết đơn nghỉ phép #{selected.request_id}
                </h3>
                <p className="text-xs text-slate-500">
                  {selected.employee_id} · {selected.full_name} ({selected.department_name})
                </p>
              </div>
              <button type="button" onClick={() => setSelected(null)}>
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>

            <dl className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <dt className="text-slate-500">Loại nghỉ</dt>
                <dd className="font-semibold">{LEAVE_TYPE_VN[selected.leave_type]}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Số ngày (ngày lịch)</dt>
                <dd className="font-semibold">{selected.leave_days} ngày</dd>
              </div>
              <div>
                <dt className="text-slate-500">Thời gian</dt>
                <dd className="font-semibold">
                  {selected.from_date} → {selected.to_date}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Trạng thái</dt>
                <dd>
                  <StatusBadge
                    label={LEAVE_STATUS_VN[selected.status]?.label ?? selected.status}
                    variant={LEAVE_STATUS_VN[selected.status]?.variant ?? 'info'}
                  />
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-slate-500">Lý do</dt>
                <dd className="mt-0.5 text-slate-800 bg-brand-bg p-2.5 rounded-lg">{selected.reason}</dd>
              </div>
              {selected.decision_note && (
                <div className="col-span-2">
                  <dt className="text-slate-500">Ghi chú phê duyệt ({selected.reviewed_by})</dt>
                  <dd className="mt-0.5 text-slate-800">{selected.decision_note}</dd>
                </div>
              )}
            </dl>

            {/* BUG-10: Approval History Timeline from leave_approval_logs */}
            <div className="pt-3 border-t border-brand-border space-y-2">
              <h4 className="text-xs font-bold text-slate-800">Lịch sử xử lý &amp; phê duyệt</h4>
              {loadingTimeline ? (
                <p className="text-[11px] text-slate-500">Đang tải lịch sử xử lý...</p>
              ) : timeline.length === 0 ? (
                <p className="text-[11px] text-slate-500">Chưa có bản ghi lịch sử phê duyệt.</p>
              ) : (
                <ol className="space-y-2 max-h-40 overflow-y-auto pr-1">
                  {timeline.map((step) => {
                    const meta = TIMELINE_ACTION_VN[step.action] ?? {
                      label: step.action,
                      variant: 'info' as BadgeVariant,
                    };
                    return (
                      <li
                        key={step.id}
                        className="rounded-lg border border-brand-border bg-brand-bg/50 px-3 py-2 text-[11px]"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <StatusBadge label={meta.label} variant={meta.variant} />
                            <span className="font-semibold text-slate-800">
                              {step.actor_name || step.actor_username || 'Hệ thống'}
                            </span>
                          </div>
                          <span className="text-[10px] font-mono text-slate-500">{step.created_at}</span>
                        </div>
                        {step.note && (
                          <p className="mt-1 text-slate-600 leading-snug">{step.note}</p>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>

            {selected.can_review && (
              <div className="pt-3 border-t border-brand-border space-y-3">
                <label className="block text-xs font-semibold text-slate-700">
                  Ghi chú quyết định (bắt buộc nếu từ chối)
                </label>
                <textarea
                  rows={2}
                  value={decisionNote}
                  onChange={(e) => setDecisionNote(e.target.value)}
                  placeholder="Nhập ghi chú phê duyệt hoặc lý do từ chối..."
                  className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border"
                />
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() => handleReview('rejected')}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-red text-white text-xs font-semibold hover:bg-red-800 disabled:opacity-50"
                  >
                    <Ban className="w-3.5 h-3.5" /> Từ chối
                  </button>
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() => handleReview('approved')}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-green text-white text-xs font-semibold hover:bg-emerald-800 disabled:opacity-50"
                  >
                    <Check className="w-3.5 h-3.5" /> Phê duyệt
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <ConfirmModal
        isOpen={Boolean(cancelTarget)}
        title="Xác nhận hủy đơn nghỉ phép"
        description={`Bạn chắc chắn muốn hủy đơn #${cancelTarget?.request_id} (${cancelTarget?.from_date} → ${cancelTarget?.to_date}) đang chờ duyệt?`}
        confirmLabel="Xác nhận hủy"
        isDanger
        isLoading={submitting}
        onConfirm={handleCancel}
        onCancel={() => setCancelTarget(null)}
      />
    </div>
  );
};
