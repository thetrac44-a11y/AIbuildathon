import React, { useCallback, useEffect, useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { BarChart3, RefreshCw, AlertTriangle, TrendingUp, Users } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { KpiCard } from '../components/ui/KpiCard';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface DeptCompareRow {
  department_id: string;
  department_name: string;
  employee_count: number;
  present_days: number;
  late_days: number;
  leave_days: number;
  absent_days: number;
  late_rate: number;
  leave_rate: number;
  on_time_rate?: number;
  open_anomalies?: number;
  total_anomalies?: number;
}

interface TrendRow {
  period: string;
  present_days: number;
  late_days: number;
  leave_days: number;
  absent_days: number;
  late_rate: number;
  leave_rate: number;
  on_time_rate: number;
}

interface SummaryPayload {
  period: string;
  kpis: {
    total_employees: number;
    on_time_rate: number;
    late_rate: number;
    absent_days: number;
    open_anomalies: number;
    high_anomalies: number;
  };
  department_chart: DeptCompareRow[];
  monthly_trend: TrendRow[];
}

export const DepartmentAnalyticsPage: React.FC = () => {
  const { selectedPeriod } = useAuth();
  const [data, setData] = useState<SummaryPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<SummaryPayload>(`/dashboard/summary?period=${selectedPeriod}`);
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải dữ liệu phân tích phòng ban.');
    } finally {
      setLoading(false);
    }
  }, [selectedPeriod]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading && !data) return <LoadingSkeleton rows={5} />;
  if (error) return <ErrorState message={error} onRetry={loadData} />;
  if (!data) return null;

  const sortedByLate = [...data.department_chart].sort((a, b) => b.late_rate - a.late_rate);
  const highestLate = sortedByLate[0];

  const columns: ColumnDef<DeptCompareRow>[] = [
    { key: 'department_name', header: 'Phòng ban', render: (r) => <span className="font-semibold text-slate-900">{r.department_name}</span> },
    { key: 'employee_count', header: 'Nhân sự' },
    { key: 'present_days', header: 'Ngày đi làm' },
    {
      key: 'late_rate',
      header: 'Tỷ lệ đi muộn',
      render: (r) => (
        <StatusBadge
          label={`${r.late_rate}% (${r.late_days} lượt)`}
          variant={r.late_rate >= 8 ? 'high' : r.late_rate >= 4 ? 'medium' : 'low'}
        />
      ),
    },
    { key: 'leave_rate', header: 'Tỷ lệ nghỉ phép', render: (r) => `${r.leave_rate}% (${r.leave_days} ngày)` },
    { key: 'absent_days', header: 'Ngày vắng', render: (r) => `${r.absent_days ?? 0} ngày` },
    {
      key: 'anomalies',
      header: 'Cảnh báo R1-R8',
      render: (r) => (
        <StatusBadge
          label={`${r.total_anomalies ?? 0} (${r.open_anomalies ?? 0} mở)`}
          variant={(r.open_anomalies ?? 0) > 0 ? 'medium' : 'approved'}
        />
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-blue/10 text-brand-blue flex items-center justify-center">
            <BarChart3 className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-900">Phân tích &amp; So sánh Phòng ban</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Góc nhìn Ban Điều hành: so sánh tỷ lệ đi muộn, nghỉ phép, vắng mặt, cảnh báo R1–R8 và xu hướng nhiều kỳ ({selectedPeriod}).
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

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          title="Tổng nhân sự toàn công ty"
          value={data.kpis.total_employees}
          subtitle={`${data.department_chart.length} phòng ban hoạt động`}
          tone="blue"
          icon={<Users className="w-5 h-5" />}
        />
        <KpiCard
          title="Tỷ lệ đi làm đúng giờ"
          value={`${data.kpis.on_time_rate}%`}
          subtitle={`Đi muộn chung: ${data.kpis.late_rate}%`}
          tone="teal"
          icon={<TrendingUp className="w-5 h-5" />}
        />
        <KpiCard
          title="Phòng đi muộn cao nhất"
          value={highestLate ? highestLate.department_name : '—'}
          subtitle={highestLate ? `${highestLate.late_rate}% (${highestLate.late_days} lượt)` : ''}
          tone="amber"
          icon={<BarChart3 className="w-5 h-5" />}
        />
        <KpiCard
          title="Cảnh báo R1-R8 đang mở"
          value={data.kpis.open_anomalies}
          subtitle={`${data.kpis.high_anomalies} mức cao · ${data.kpis.absent_days} ngày vắng`}
          tone="red"
          icon={<AlertTriangle className="w-5 h-5" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-slate-900">So sánh tỷ lệ đi muộn &amp; nghỉ phép theo phòng</h3>
          <p className="text-xs text-slate-500 mb-3">Kỳ {selectedPeriod}</p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.department_chart}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E4EAF2" />
                <XAxis dataKey="department_name" tick={{ fontSize: 11, fill: '#475569' }} />
                <YAxis tick={{ fontSize: 11, fill: '#475569' }} unit="%" />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="late_rate" name="Tỷ lệ đi muộn (%)" fill="#2563EB" radius={[5, 5, 0, 0]} />
                <Bar dataKey="leave_rate" name="Tỷ lệ nghỉ phép (%)" fill="#0F9D9A" radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-slate-900">Xu hướng tỷ lệ đi muộn theo tháng</h3>
          <p className="text-xs text-slate-500 mb-3">Dữ liệu lịch sử toàn công ty</p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.monthly_trend ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E4EAF2" />
                <XAxis dataKey="period" tick={{ fontSize: 11, fill: '#475569' }} />
                <YAxis tick={{ fontSize: 11, fill: '#475569' }} unit="%" />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="late_rate" name="Tỷ lệ đi muộn (%)" fill="#B45309" radius={[5, 5, 0, 0]} />
                <Bar dataKey="leave_rate" name="Tỷ lệ nghỉ phép (%)" fill="#2563EB" radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="space-y-2.5">
        <h3 className="text-sm font-bold text-slate-900">Bảng so sánh chi tiết các phòng ban ({selectedPeriod})</h3>
        <DataTable columns={columns} data={sortedByLate} rowKey={(r) => r.department_id} />
      </div>
    </div>
  );
};
