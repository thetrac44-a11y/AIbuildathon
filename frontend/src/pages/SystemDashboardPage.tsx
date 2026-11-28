import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BookOpen,
  Camera,
  Database,
  KeyRound,
  RefreshCw,
  ScrollText,
  ServerCog,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { apiFetch, ApiError } from '../lib/api';
import { KpiCard } from '../components/ui/KpiCard';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface SystemDashboardPayload {
  scope: string;
  database_engine: string;
  health: string;
  kpis: {
    total_accounts: number;
    active_accounts: number;
    locked_accounts: number;
    roles_count: number;
    permissions_count: number;
    activity_logs_count: number;
    query_audit_count: number;
    blocked_query_count: number;
    rag_documents_count: number;
    rag_chunks_count: number;
    kiosk_devices_total: number;
    kiosk_devices_active: number;
  };
  accounts_by_role: {
    role: string;
    total_accounts: number;
    active_accounts: number;
    locked_accounts: number;
  }[];
  recent_security_events: {
    id: number;
    actor_user_id: string;
    actor_username: string | null;
    action: string;
    entity_type: string;
    entity_id: string;
    created_at: string;
  }[];
}

const ROLE_NAME: Record<string, string> = {
  employee: 'Nhân viên (employee)',
  manager: 'Trưởng phòng (manager)',
  hr: 'Nhân sự (hr)',
  executive: 'Cấp lãnh đạo (executive)',
  admin: 'Quản trị hệ thống (admin)',
};

export const SystemDashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const [data, setData] = useState<SystemDashboardPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<SystemDashboardPayload>('/admin/system-dashboard');
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải bảng điều khiển hệ thống.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading && !data) return <LoadingSkeleton rows={5} />;
  if (error) return <ErrorState message={error} onRetry={loadData} />;
  if (!data) return null;

  const k = data.kpis;
  const roleCols: ColumnDef<SystemDashboardPayload['accounts_by_role'][0]>[] = [
    { key: 'role', header: 'Vai trò RBAC', render: (r) => <span className="font-semibold text-slate-900">{ROLE_NAME[r.role] ?? r.role}</span> },
    { key: 'total_accounts', header: 'Tổng tài khoản' },
    { key: 'active_accounts', header: 'Đang hoạt động', render: (r) => <StatusBadge label={String(r.active_accounts)} variant="approved" /> },
    { key: 'locked_accounts', header: 'Đã khóa', render: (r) => <StatusBadge label={String(r.locked_accounts)} variant={r.locked_accounts > 0 ? 'rejected' : 'dismissed'} /> },
  ];

  const eventCols: ColumnDef<SystemDashboardPayload['recent_security_events'][0]>[] = [
    { key: 'created_at', header: 'Thời gian' },
    { key: 'actor_username', header: 'Người thực hiện', render: (r) => r.actor_username || r.actor_user_id },
    { key: 'action', header: 'Hành động', render: (r) => <StatusBadge label={r.action} variant="info" /> },
    { key: 'entity_type', header: 'Đối tượng' },
    { key: 'entity_id', header: 'Mã', render: (r) => <span className="font-mono text-[11px]">{r.entity_id}</span> },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/10 text-brand-navy flex items-center justify-center">
            <ServerCog className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">System Dashboard – Quản trị kỹ thuật</h2>
              <StatusBadge label={data.health === 'healthy' ? 'Hệ thống ổn định' : data.health} variant="approved" />
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              CSDL đang kết nối: <strong className="text-slate-700">{data.database_engine}</strong> · Tách bạch hoàn toàn quản trị kỹ thuật khỏi dữ liệu nghiệp vụ HR.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={loadData}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-brand-border bg-white text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Làm mới
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
        <KpiCard
          title="Tài khoản hệ thống"
          value={k.total_accounts}
          subtitle={`${k.active_accounts} hoạt động · ${k.locked_accounts} khóa`}
          tone="blue"
          icon={<Users className="w-5 h-5" />}
          onClick={() => navigate('/admin/accounts')}
        />
        <KpiCard
          title="Vai trò & Quyền RBAC"
          value={`${k.roles_count} roles`}
          subtitle={`${k.permissions_count} permissions chuẩn`}
          tone="teal"
          icon={<KeyRound className="w-5 h-5" />}
          onClick={() => navigate('/admin/rbac')}
        />
        <KpiCard
          title="Nhật ký kiểm toán"
          value={k.activity_logs_count}
          subtitle={`${k.query_audit_count} AI queries · ${k.blocked_query_count} bị chặn`}
          tone="amber"
          icon={<ScrollText className="w-5 h-5" />}
          onClick={() => navigate('/admin/audit')}
        />
        <KpiCard
          title="Kho tài liệu RAG"
          value={k.rag_documents_count}
          subtitle={`${k.rag_chunks_count} chunks đã đánh chỉ mục`}
          tone="green"
          icon={<BookOpen className="w-5 h-5" />}
          onClick={() => navigate('/admin/rag')}
        />
        <KpiCard
          title="Thiết bị Face Kiosk"
          value={`${k.kiosk_devices_active}/${k.kiosk_devices_total}`}
          subtitle="Thiết bị đang hoạt động"
          tone="blue"
          icon={<Camera className="w-5 h-5" />}
          onClick={() => navigate('/admin/kiosk')}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4 text-brand-blue" /> Phân bổ tài khoản theo 5 vai trò
            </h3>
            <button type="button" onClick={() => navigate('/admin/accounts')} className="text-xs font-semibold text-brand-blue hover:underline">
              Quản lý tài khoản →
            </button>
          </div>
          <DataTable columns={roleCols} data={data.accounts_by_role} rowKey={(r) => r.role} />
        </div>

        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
              <Database className="w-4 h-4 text-brand-teal" /> Sự kiện kiểm toán gần nhất
            </h3>
            <button type="button" onClick={() => navigate('/admin/audit')} className="text-xs font-semibold text-brand-blue hover:underline">
              Xem tất cả audit →
            </button>
          </div>
          <DataTable columns={eventCols} data={data.recent_security_events} rowKey={(r) => String(r.id)} />
        </div>
      </div>
    </div>
  );
};
