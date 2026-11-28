import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Database, ScrollText, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { hasPermission } from '../config/navigation';
import { apiFetch, ApiError } from '../lib/api';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface ActivityRow {
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

interface QueryAuditRow {
  id: number;
  asked_at: string;
  user_id: string;
  username: string | null;
  role: string;
  query_text: string;
  query_type: string;
  tool_name: string | null;
  sql_text: string | null;
  scope: string;
  result_count: number;
  success: boolean;
  status: string;
}

export const AuditLogsPage: React.FC = () => {
  const { user } = useAuth();
  const canViewQueryAudit = hasPermission(user, 'audit.read');
  const [tab, setTab] = useState<'activity' | 'queries'>('activity');
  const [activities, setActivities] = useState<ActivityRow[]>([]);
  const [queries, setQueries] = useState<QueryAuditRow[]>([]);
  const [roleFilter, setRoleFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedActivity, setSelectedActivity] = useState<ActivityRow | null>(null);
  const [selectedQuery, setSelectedQuery] = useState<QueryAuditRow | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === 'activity') {
        const res = await apiFetch<{ items: ActivityRow[] }>('/audit/activity?limit=100');
        setActivities(res.items || []);
      } else {
        const qs = new URLSearchParams({ limit: '100' });
        if (roleFilter !== 'all') qs.set('role', roleFilter);
        const res = await apiFetch<{ items: QueryAuditRow[] }>(`/audit/queries?${qs.toString()}`);
        setQueries(res.items || []);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải nhật ký kiểm toán.');
    } finally {
      setLoading(false);
    }
  }, [tab, roleFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const actCols: ColumnDef<ActivityRow>[] = [
    { key: 'created_at', header: 'Thời gian' },
    { key: 'actor_username', header: 'Người thực hiện', render: (r) => r.actor_username || r.actor_user_id },
    { key: 'action', header: 'Hành động', render: (r) => <StatusBadge label={r.action} variant="info" /> },
    { key: 'entity_type', header: 'Đối tượng' },
    { key: 'entity_id', header: 'Mã', render: (r) => <span className="font-mono text-[11px]">{r.entity_id}</span> },
    {
      key: 'detail',
      header: 'Chi tiết',
      render: (r) => (
        <button type="button" onClick={() => setSelectedActivity(r)} className="text-brand-blue font-semibold hover:underline">
          Xem JSON
        </button>
      ),
    },
  ];

  const qCols: ColumnDef<QueryAuditRow>[] = [
    { key: 'asked_at', header: 'Thời gian' },
    { key: 'username', header: 'Người dùng', render: (r) => r.username || r.user_id },
    { key: 'role', header: 'Vai trò', render: (r) => <StatusBadge label={r.role.toUpperCase()} variant="info" /> },
    { key: 'scope', header: 'Phạm vi' },
    { key: 'query_text', header: 'Nội dung truy vấn', render: (r) => <span className="block max-w-xs truncate">{r.query_text}</span> },
    { key: 'tool_name', header: 'SQL Tool', render: (r) => <span className="font-mono text-[11px]">{r.tool_name || '—'}</span> },
    { key: 'result_count', header: 'Số dòng' },
    {
      key: 'status',
      header: 'Kết quả',
      render: (r) => (
        <StatusBadge
          label={r.status}
          variant={r.status === 'success' ? 'approved' : r.status === 'blocked' ? 'rejected' : 'medium'}
        />
      ),
    },
    {
      key: 'sql',
      header: 'SQL Trace',
      render: (r) => (
        <button type="button" onClick={() => setSelectedQuery(r)} className="text-brand-blue font-semibold hover:underline">
          Xem
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/10 text-brand-navy flex items-center justify-center">
            <ScrollText className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-900">Nhật ký Kiểm toán (Audit Logs)</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Theo dõi thay đổi tài khoản, phân quyền, cấu hình hệ thống và truy vấn AI SQL Guard (không lưu mật khẩu/secret).
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setTab('activity')}
            className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold ${
              tab === 'activity' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            <Activity className="w-3.5 h-3.5" /> Activity Logs
          </button>
          {canViewQueryAudit && (
            <button
              type="button"
              onClick={() => setTab('queries')}
              className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold ${
                tab === 'queries' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              <Database className="w-3.5 h-3.5" /> Query Audit Logs
            </button>
          )}
        </div>
      </div>

      {tab === 'queries' && canViewQueryAudit && (
        <div className="flex items-center gap-3 bg-white border border-brand-border rounded-card px-4 py-3 text-xs">
          <span className="font-semibold text-slate-700">Lọc theo vai trò:</span>
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="px-3 py-1.5 rounded-lg border border-brand-border bg-brand-bg/60"
          >
            <option value="all">Tất cả 5 vai trò</option>
            <option value="employee">Employee</option>
            <option value="manager">Manager</option>
            <option value="hr">HR</option>
            <option value="executive">Executive</option>
            <option value="admin">Admin</option>
          </select>
        </div>
      )}

      {loading && <LoadingSkeleton rows={5} />}
      {!loading && error && <ErrorState message={error} onRetry={loadData} />}
      {!loading && !error && tab === 'activity' && (
        <DataTable columns={actCols} data={activities} rowKey={(r) => String(r.id)} emptyTitle="Chưa có nhật ký hoạt động" />
      )}
      {!loading && !error && tab === 'queries' && (
        <DataTable columns={qCols} data={queries} rowKey={(r) => String(r.id)} emptyTitle="Chưa có nhật ký truy vấn AI" />
      )}

      {selectedActivity && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-lg rounded-card border border-brand-border bg-white p-6 shadow-xl space-y-3 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-brand-border">
              <h3 className="text-sm font-bold text-slate-900">Chi tiết Activity #{selectedActivity.id}</h3>
              <button type="button" onClick={() => setSelectedActivity(null)}><X className="w-4 h-4" /></button>
            </div>
            <p><strong>Trước:</strong></p>
            <pre className="p-2.5 rounded-lg bg-slate-50 border border-brand-border overflow-x-auto text-[11px]">{selectedActivity.before_json || 'null'}</pre>
            <p><strong>Sau:</strong></p>
            <pre className="p-2.5 rounded-lg bg-slate-50 border border-brand-border overflow-x-auto text-[11px]">{selectedActivity.after_json || 'null'}</pre>
          </div>
        </div>
      )}

      {selectedQuery && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-lg rounded-card border border-brand-border bg-white p-6 shadow-xl space-y-3 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-brand-border">
              <h3 className="text-sm font-bold text-slate-900">Query Audit #{selectedQuery.id}</h3>
              <button type="button" onClick={() => setSelectedQuery(null)}><X className="w-4 h-4" /></button>
            </div>
            <p><strong>Câu hỏi:</strong> {selectedQuery.query_text}</p>
            <p><strong>Loại / Phạm vi:</strong> {selectedQuery.query_type} · {selectedQuery.scope}</p>
            <p><strong>SQL đã thực thi:</strong></p>
            <pre className="p-2.5 rounded-lg bg-slate-50 border border-brand-border overflow-x-auto text-[11px] whitespace-pre-wrap">{selectedQuery.sql_text || '(Không chạy SQL — bị chặn hoặc yêu cầu làm rõ)'}</pre>
          </div>
        </div>
      )}
    </div>
  );
};
