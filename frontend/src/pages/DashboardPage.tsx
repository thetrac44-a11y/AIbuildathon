import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import { Users, Clock, AlertTriangle, CalendarDays, RefreshCw } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { KpiCard } from '../components/ui/KpiCard';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';
import { EmptyState } from '../components/ui/EmptyState';

interface DashboardSummary {
  period: string;
  role: string;
  kpis: {
    total_employees: number;
    total_work_hours: number;
    present_days: number;
    on_time_days: number;
    on_time_rate: number;
    late_days: number;
    late_rate: number;
    leave_days: number;
    absent_days: number;
    missing_punch_days: number;
    pending_leaves: number;
    pending_leaves_in_period?: number;
    open_anomalies: number;
    high_anomalies: number;
    remaining_annual_leave: number;
  };
  status_distribution: { name: string; value: number }[];
  department_chart: {
    department_id: string;
    department_name: string;
    employee_count: number;
    present_days: number;
    late_days: number;
    leave_days: number;
    leave_rate: number;
    late_rate: number;
  }[];
  top_alerts: {
    anomaly_id: number;
    employee_id: string | null;
    full_name: string | null;
    department_name: string | null;
    scope_type: string;
    rule_code: string;
    anomaly_type: string;
    severity: 'high' | 'medium' | 'low';
    review_status: string;
  }[];
  calendar_days: {
    work_date: string;
    status: string;
    is_late: number;
    late_minutes: number;
    work_hours: number;
    check_in: string | null;
    check_out: string | null;
  }[];
}

const PIE_COLORS = ['#2563EB', '#B45309', '#0F9D9A', '#B91C1C'];

const SEVERITY_LABEL: Record<string, string> = {
  high: 'Cao',
  medium: 'Trung bình',
  low: 'Thấp',
};

export const DashboardPage: React.FC = () => {
  const { user, selectedPeriod } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [departments, setDepartments] = useState<{ department_id: string; name: string }[]>([]);
  const [selectedDept, setSelectedDept] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.role === 'hr') {
      apiFetch<{ items: { department_id: string; name: string }[] }>('/departments')
        .then((res) => setDepartments(res.items))
        .catch(() => {});
    }
  }, [user?.role]);

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ period: selectedPeriod });
      if (user?.role === 'hr' && selectedDept) {
        qs.set('department_id', selectedDept);
      }
      const res = await apiFetch<DashboardSummary>(`/dashboard/summary?${qs.toString()}`);
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải dữ liệu tổng quan.');
    } finally {
      setLoading(false);
    }
  }, [selectedPeriod, selectedDept, user?.role]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  if (loading && !data) {
    return <LoadingSkeleton rows={5} />;
  }
  if (error) {
    return <ErrorState message={error} onRetry={fetchSummary} />;
  }
  if (!data || !user) return null;

  const k = data.kpis;
  const isEmployee = user.role === 'employee';

  return (
    <div className="space-y-5">
      {/* Top Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            {isEmployee
              ? `Tổng quan cá nhân – ${user.full_name} (${user.employee_id})`
              : user.role === 'manager'
                ? `Tổng quan Phòng ${user.department_name}`
                : 'Tổng quan Chấm công & Nhân sự Toàn công ty'}
          </h2>
          <p className="text-xs text-slate-500">
            Số liệu được tính trực tiếp bằng SQL/Python cho kỳ {selectedPeriod}.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {user.role === 'hr' && (
            <select
              aria-label="Lọc theo phòng ban"
              value={selectedDept}
              onChange={(e) => setSelectedDept(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-brand-border bg-white text-xs text-slate-700"
            >
              <option value="">Tất cả phòng ban</option>
              {departments.map((d) => (
                <option key={d.department_id} value={d.department_id}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={fetchSummary}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-brand-border bg-white text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Làm mới
          </button>
        </div>
      </div>

      {/* 4 KPI Cards */}
      {isEmployee ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <KpiCard
            title="Tổng giờ công"
            value={`${k.total_work_hours} giờ`}
            subtitle={`Kỳ ${selectedPeriod}`}
            tooltip="Tổng số giờ làm việc thực tế (đã trừ 1h nghỉ trưa)"
            tone="blue"
            icon={<Clock className="w-5 h-5" />}
            onClick={() => navigate('/attendance')}
          />
          <KpiCard
            title="Ngày đi làm"
            value={`${k.present_days} ngày`}
            subtitle={`Đúng giờ: ${k.on_time_days} ngày`}
            tooltip="Số ngày có trạng thái present trong kỳ"
            tone="teal"
            icon={<CalendarDays className="w-5 h-5" />}
            onClick={() => navigate('/attendance')}
          />
          <KpiCard
            title="Số lần đi muộn"
            value={`${k.late_days} lần`}
            subtitle={`Tỷ lệ: ${k.late_rate}% (>5 phút)`}
            tooltip="Vào sau 08:35:00 mới tính đi muộn"
            tone="amber"
            icon={<AlertTriangle className="w-5 h-5" />}
            onClick={() => navigate('/attendance')}
          />
          <KpiCard
            title="Phép năm còn lại"
            value={`${k.remaining_annual_leave} ngày`}
            subtitle={`Đơn chờ duyệt: ${k.pending_leaves}`}
            tooltip="Quỹ phép năm trừ các đơn phép năm đã duyệt (theo ngày lịch)"
            tone="green"
            icon={<CalendarDays className="w-5 h-5" />}
            onClick={() => navigate('/leaves')}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          <KpiCard
            title={user.role === 'manager' ? 'Nhân sự trong phòng' : 'Tổng nhân viên'}
            value={k.total_employees}
            subtitle={user.role === 'manager' ? `Phòng ${user.department_name}` : `${data.department_chart.length} phòng ban`}
            tooltip="Số nhân viên đang hoạt động trong phạm vi"
            tone="blue"
            icon={<Users className="w-5 h-5" />}
            onClick={() => navigate('/admin/employees')}
          />
          <KpiCard
            title="Tổng giờ công"
            value={k.total_work_hours.toLocaleString('vi-VN')}
            subtitle={`Đúng giờ: ${k.on_time_rate}%`}
            tooltip="Tổng giờ công làm việc thực tế trong kỳ đã chọn"
            tone="teal"
            icon={<Clock className="w-5 h-5" />}
            onClick={() => navigate('/attendance')}
          />
          <KpiCard
            title="Tỷ lệ đi muộn"
            value={`${k.late_rate}%`}
            subtitle={`${k.late_days} lượt · ${k.leave_days} ngày phép`}
            tooltip="Số lượt đi muộn (>5 phút) / Tổng ngày đi làm"
            tone="amber"
            icon={<CalendarDays className="w-5 h-5" />}
            onClick={() => navigate('/attendance')}
          />
          <KpiCard
            title="Cảnh báo bất thường mở"
            value={k.open_anomalies}
            subtitle={`${k.high_anomalies} mức cao · kỳ ${selectedPeriod}`}
            tooltip="Cảnh báo bất thường R1–R8 đang ở trạng thái Mở trong kỳ đã chọn"
            tone="red"
            icon={<AlertTriangle className="w-5 h-5" />}
            onClick={() => navigate('/anomalies')}
          />
          <KpiCard
            title="Đơn nghỉ phép chờ duyệt"
            value={k.pending_leaves}
            subtitle={`Trong kỳ ${selectedPeriod}: ${k.pending_leaves_in_period ?? 0} đơn`}
            tooltip="Tổng số đơn nghỉ phép đang ở trạng thái Chờ duyệt cần xử lý trong phạm vi"
            tone="green"
            icon={<CalendarDays className="w-5 h-5" />}
            onClick={() => navigate('/leaves')}
          />
        </div>
      )}

      {/* Middle Visuals */}
      {isEmployee ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 rounded-card border border-brand-border bg-white p-5 shadow-sm">
            <h3 className="text-sm font-bold text-slate-900 mb-3">
              Lịch chấm công trong tháng ({selectedPeriod})
            </h3>
            {data.calendar_days.length === 0 ? (
              <EmptyState title="Không có dữ liệu chấm công trong tháng này" />
            ) : (
              <>
                <div className="grid grid-cols-4 sm:grid-cols-7 gap-2">
                  {data.calendar_days.map((day) => {
                    const dayNum = day.work_date.slice(-2);
                    const isMissingPunch =
                      day.status === 'present' && (!day.check_in || !day.check_out);
                    let badgeCls = 'bg-emerald-50 border-emerald-200 text-brand-green';
                    let label = `${day.work_hours}h`;
                    if (day.status === 'on_leave') {
                      badgeCls = 'bg-blue-50 border-blue-200 text-brand-blue';
                      label = 'Phép';
                    } else if (day.status === 'holiday') {
                      badgeCls = 'bg-slate-100 border-slate-200 text-slate-600';
                      label = 'Lễ';
                    } else if (day.status === 'absent') {
                      badgeCls = 'bg-red-50 border-red-200 text-brand-red';
                      label = 'Vắng';
                    } else if (isMissingPunch) {
                      badgeCls = 'bg-purple-50 border-purple-300 text-purple-800';
                      label = 'Thiếu CC';
                    } else if (day.is_late === 1) {
                      badgeCls = 'bg-amber-50 border-amber-200 text-brand-amber';
                      label = `+${day.late_minutes}p`;
                    }
                    return (
                      <div
                        key={day.work_date}
                        title={`${day.work_date}: ${day.check_in || 'Thiếu giờ vào'} → ${day.check_out || 'Thiếu giờ ra'}`}
                        className={`rounded-xl border p-2 text-center ${badgeCls}`}
                      >
                        <p className="text-xs font-bold">{dayNum}</p>
                        <p className="text-[10px] font-medium mt-0.5">{label}</p>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-4 pt-3 border-t border-brand-border flex flex-wrap items-center gap-3 text-[11px] text-slate-600">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-emerald-100 border border-emerald-300" />
                    Đúng giờ
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-amber-100 border border-amber-300" />
                    Đi muộn (&gt;5p)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-purple-100 border border-purple-300" />
                    Thiếu CC (thiếu giờ vào/ra)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-blue-100 border border-blue-300" />
                    Nghỉ phép
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-red-100 border border-red-300" />
                    Vắng mặt
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-slate-200 border border-slate-300" />
                    Ngày lễ
                  </span>
                </div>
              </>
            )}
          </div>

          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm space-y-3">
            <h3 className="text-sm font-bold text-slate-900">Thông tin nhanh</h3>
            <dl className="space-y-2.5 text-xs">
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Quản lý trực tiếp</dt>
                <dd className="font-semibold text-slate-800">{user.manager_name || 'Ban Giám đốc'}</dd>
              </div>
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Phòng ban</dt>
                <dd className="font-semibold text-slate-800">{user.department_name}</dd>
              </div>
              <div className="flex justify-between py-1.5 border-b border-brand-border">
                <dt className="text-slate-500">Trạng thái tài khoản</dt>
                <dd>
                  <StatusBadge label="Hoạt động" variant="approved" />
                </dd>
              </div>
              <div className="flex justify-between py-1.5">
                <dt className="text-slate-500">Cảnh báo cá nhân mở</dt>
                <dd className="font-bold text-brand-amber">{k.open_anomalies}</dd>
              </div>
            </dl>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 rounded-card border border-brand-border bg-white p-5 shadow-sm">
            <h3 className="text-sm font-bold text-slate-900">Tỷ lệ đi muộn (%) theo phòng ban</h3>
            <p className="text-xs text-slate-500 mb-4">So sánh trong kỳ {selectedPeriod}</p>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.department_chart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E4EAF2" />
                  <XAxis dataKey="department_name" tick={{ fontSize: 11, fill: '#475569' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#475569' }} unit="%" />
                  <Tooltip />
                  <Bar dataKey="late_rate" name="Tỷ lệ đi muộn (%)" fill="#2563EB" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
            <h3 className="text-sm font-bold text-slate-900">Phân bố trạng thái chấm công</h3>
            <p className="text-xs text-slate-500 mb-2">Kỳ {selectedPeriod}</p>
            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.status_distribution}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={72}
                    paddingAngle={2}
                  >
                    {data.status_distribution.map((_, idx) => (
                      <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs mt-1">
              {data.status_distribution.map((s, idx) => (
                <div key={s.name} className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-slate-600">
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: PIE_COLORS[idx % PIE_COLORS.length] }}
                    />
                    {s.name}
                  </span>
                  <span className="font-semibold text-slate-800">{s.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Top Alerts Card */}
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold text-slate-900">Cảnh báo nổi bật cần xem xét</h3>
          <button
            type="button"
            onClick={() => navigate('/anomalies')}
            className="text-xs font-semibold text-brand-blue hover:underline"
          >
            Xem tất cả →
          </button>
        </div>
        {data.top_alerts.length === 0 ? (
          <EmptyState
            title="Không có cảnh báo đang mở trong kỳ này"
            description="Tất cả cảnh báo trong phạm vi đã được xử lý hoặc chưa phát sinh bất thường."
          />
        ) : (
          <div className="divide-y divide-brand-border">
            {data.top_alerts.map((al) => (
              <div
                key={al.anomaly_id}
                onClick={() => navigate(`/anomalies/${al.anomaly_id}`)}
                className="py-3 flex items-center justify-between gap-3 cursor-pointer hover:bg-slate-50 px-2 rounded-lg"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <StatusBadge label={al.rule_code} variant="info" />
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-800 truncate">
                      {al.scope_type === 'department'
                        ? `Cấp phòng: ${al.department_name}`
                        : `${al.employee_id} · ${al.full_name}`}
                    </p>
                    <p className="text-[11px] text-slate-500">{al.anomaly_type}</p>
                  </div>
                </div>
                <StatusBadge
                  label={SEVERITY_LABEL[al.severity] ?? al.severity}
                  variant={al.severity}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
