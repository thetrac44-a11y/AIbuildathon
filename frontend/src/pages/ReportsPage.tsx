import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  Info,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { hasPermission } from '../config/navigation';
import { apiDownload, apiFetch, ApiError } from '../lib/api';
import { KpiCard } from '../components/ui/KpiCard';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface DepartmentOption {
  department_id: string;
  name: string;
}

interface DepartmentMetric {
  department_id: string;
  department_name: string;
  employee_count: number;
  total_work_hours: number;
  present_days: number;
  late_days: number;
  late_rate_pct: number;
  leave_days: number;
  absent_days: number;
}

interface TopLateEmployee {
  employee_id: string;
  full_name: string;
  department_name: string;
  late_days: number;
  total_late_minutes: number;
  avg_late_minutes: number;
}

interface ReportAnomaly {
  anomaly_id: number;
  rule_code: string;
  anomaly_type: string;
  scope_type: string;
  target_code: string;
  target_name: string;
  department_name: string;
  severity: 'high' | 'medium' | 'low';
  review_status: 'open' | 'confirmed' | 'dismissed';
  explanation: string;
}

interface ReportPreviewData {
  period: string;
  scope_label: string;
  department_id: string | null;
  generated_by: string;
  generated_at: string;
  kpis: {
    employee_count: number;
    total_work_hours: number;
    present_days: number;
    on_time_days: number;
    late_days: number;
    late_rate_pct: number;
    leave_days: number;
    leave_rate_pct: number;
    absent_days: number;
    missing_punch_days: number;
    total_anomalies: number;
    open_anomalies: number;
    high_anomalies: number;
  };
  department_metrics: DepartmentMetric[];
  top_late_employees: TopLateEmployee[];
  anomalies: ReportAnomaly[];
  narrative: {
    text: string;
    verified: boolean;
    used_fallback: boolean;
    flagged_unverified_numbers: string[];
    checked_count: number;
  };
  definitions: {
    standard_shift: string;
    late_rate_pct: string;
    leave_days: string;
  };
}

export const ReportsPage: React.FC = () => {
  const { user, selectedPeriod, showToast } = useAuth();
  const canFilterAllDepts = hasPermission(user, 'report.read.all');

  const [departments, setDepartments] = useState<DepartmentOption[]>([]);
  const [selectedDept, setSelectedDept] = useState<string>('');
  const [report, setReport] = useState<ReportPreviewData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<'pdf' | 'excel' | null>(null);

  useEffect(() => {
    if (!canFilterAllDepts) return;
    apiFetch<{ items: DepartmentOption[] }>('/departments')
      .then((res) => setDepartments(res.items || []))
      .catch(() => {
        // Ignore non-critical department list error
      });
  }, [canFilterAllDepts]);

  const loadReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ period: selectedPeriod });
      if (canFilterAllDepts && selectedDept) {
        qs.set('department_id', selectedDept);
      }
      const data = await apiFetch<ReportPreviewData>(`/reports/preview?${qs.toString()}`);
      setReport(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải xem trước báo cáo.');
    } finally {
      setLoading(false);
    }
  }, [selectedPeriod, canFilterAllDepts, selectedDept]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const handleExport = async (format: 'pdf' | 'excel') => {
    setExporting(format);
    try {
      const qs = new URLSearchParams({ period: selectedPeriod });
      if (canFilterAllDepts && selectedDept) {
        qs.set('department_id', selectedDept);
      }
      const ext = format === 'pdf' ? 'pdf' : 'xlsx';
      await apiDownload(
        `/reports/export/${format}?${qs.toString()}`,
        `bao_cao_cham_cong_${selectedPeriod}.${ext}`
      );
      showToast(
        `Đã tải xuống báo cáo ${format === 'pdf' ? 'PDF tiếng Việt' : 'Excel 4 sheet'} kỳ ${selectedPeriod}.`,
        'success'
      );
    } catch (err) {
      showToast(
        err instanceof ApiError ? err.message : 'Xuất báo cáo thất bại. Vui lòng thử lại.',
        'error'
      );
    } finally {
      setExporting(null);
    }
  };

  const deptColumns: ColumnDef<DepartmentMetric>[] = [
    { key: 'department_name', header: 'Phòng ban', render: (r) => <span className="font-semibold text-slate-900">{r.department_name}</span> },
    { key: 'employee_count', header: 'Nhân sự' },
    { key: 'total_work_hours', header: 'Tổng giờ công', render: (r) => `${r.total_work_hours.toLocaleString('vi-VN')} giờ` },
    { key: 'present_days', header: 'Ngày đi làm' },
    { key: 'late_days', header: 'Lượt đi muộn' },
    {
      key: 'late_rate_pct',
      header: 'Tỷ lệ muộn',
      render: (r) => (
        <StatusBadge
          label={`${r.late_rate_pct}%`}
          variant={r.late_rate_pct >= 10 ? 'high' : r.late_rate_pct >= 5 ? 'medium' : 'low'}
        />
      ),
    },
    { key: 'leave_days', header: 'Ngày nghỉ phép' },
    { key: 'absent_days', header: 'Ngày vắng' },
  ];

  const topLateColumns: ColumnDef<TopLateEmployee>[] = [
    { key: 'employee_id', header: 'Mã NV', render: (r) => <span className="font-mono font-semibold text-brand-navy">{r.employee_id}</span> },
    { key: 'full_name', header: 'Họ và tên', render: (r) => <span className="font-medium text-slate-900">{r.full_name}</span> },
    { key: 'department_name', header: 'Phòng ban' },
    {
      key: 'late_days',
      header: 'Số lần đi muộn',
      render: (r) => <StatusBadge label={`${r.late_days} lần`} variant={r.late_days >= 5 ? 'high' : 'medium'} />,
    },
    { key: 'total_late_minutes', header: 'Tổng phút muộn', render: (r) => `${r.total_late_minutes} phút` },
    { key: 'avg_late_minutes', header: 'Trung bình/lần', render: (r) => `${r.avg_late_minutes} phút` },
  ];

  const anomalyColumns: ColumnDef<ReportAnomaly>[] = [
    { key: 'rule_code', header: 'Quy tắc', render: (r) => <StatusBadge label={r.rule_code} variant="info" /> },
    {
      key: 'target_name',
      header: 'Đối tượng cần rà soát',
      render: (r) => (
        <div>
          <span className="font-semibold text-slate-900">{r.target_name}</span>
          <span className="ml-1.5 text-[11px] text-slate-500">({r.target_code})</span>
        </div>
      ),
    },
    { key: 'department_name', header: 'Phòng ban' },
    {
      key: 'severity',
      header: 'Mức ưu tiên',
      render: (r) => (
        <StatusBadge
          label={r.severity === 'high' ? 'Cao' : r.severity === 'medium' ? 'Trung bình' : 'Thấp'}
          variant={r.severity}
        />
      ),
    },
    {
      key: 'review_status',
      header: 'Trạng thái',
      render: (r) => (
        <StatusBadge
          label={r.review_status === 'open' ? 'Cần xem xét' : r.review_status === 'confirmed' ? 'Đã xác nhận' : 'Đã bỏ qua'}
          variant={r.review_status}
        />
      ),
    },
    {
      key: 'explanation',
      header: 'Ghi nhận hệ thống',
      render: (r) => <span className="block max-w-md whitespace-normal text-slate-600">{r.explanation}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header & Actions */}
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold text-slate-900">Báo cáo Chấm công & Nhân sự</h2>
            <StatusBadge label={`Kỳ ${selectedPeriod}`} variant="info" />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            100% số liệu tổng hợp trực tiếp từ SQL theo phạm vi phân quyền. Văn bản tóm tắt được kiểm chứng khớp số liệu trước khi xuất PDF/Excel.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {canFilterAllDepts && (
            <select
              aria-label="Lọc phòng ban báo cáo"
              value={selectedDept}
              onChange={(e) => setSelectedDept(e.target.value)}
              className="px-3 py-2 text-xs rounded-lg border border-brand-border bg-brand-bg/60 text-slate-700 focus:outline-none focus:border-brand-blue"
            >
              <option value="">Toàn công ty</option>
              {departments.map((d) => (
                <option key={d.department_id} value={d.department_id}>
                  Phòng {d.name}
                </option>
              ))}
            </select>
          )}

          <button
            type="button"
            disabled={loading || exporting !== null}
            onClick={() => handleExport('pdf')}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-navy text-white text-xs font-semibold hover:bg-slate-800 disabled:opacity-50 transition-colors"
          >
            <FileText className="w-4 h-4" />
            {exporting === 'pdf' ? 'Đang xuất PDF...' : 'Xuất PDF'}
          </button>

          <button
            type="button"
            disabled={loading || exporting !== null}
            onClick={() => handleExport('excel')}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-teal text-white text-xs font-semibold hover:bg-teal-700 disabled:opacity-50 transition-colors"
          >
            <FileSpreadsheet className="w-4 h-4" />
            {exporting === 'excel' ? 'Đang xuất Excel...' : 'Xuất Excel (.xlsx)'}
          </button>
        </div>
      </div>

      {loading && <LoadingSkeleton rows={5} />}
      {!loading && error && <ErrorState message={error} onRetry={loadReport} />}

      {!loading && !error && report && (
        <>
          {/* Scope metadata */}
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 rounded-lg bg-slate-100/80 border border-brand-border text-xs text-slate-600">
            <div className="flex flex-wrap items-center gap-4">
              <span>
                Phạm vi: <strong className="text-slate-900">{report.scope_label}</strong>
              </span>
              <span>
                Người lập: <strong className="text-slate-900">{report.generated_by}</strong>
              </span>
            </div>
            <span className="text-[11px] text-slate-500">Cập nhật lúc: {report.generated_at}</span>
          </div>

          {/* 4 KPI cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              title="Tổng giờ công thực tế"
              value={`${report.kpis.total_work_hours.toLocaleString('vi-VN')}h`}
              subtitle={`${report.kpis.employee_count} nhân sự • ${report.kpis.present_days} ngày đi làm`}
              tooltip={report.definitions.standard_shift}
              tone="blue"
              icon={<Clock className="w-5 h-5" />}
            />
            <KpiCard
              title="Tỷ lệ đi muộn"
              value={`${report.kpis.late_rate_pct}%`}
              subtitle={`${report.kpis.late_days} lượt đi muộn (>5 phút)`}
              tooltip={report.definitions.late_rate_pct}
              tone={report.kpis.late_rate_pct >= 8 ? 'amber' : 'teal'}
              icon={<Users className="w-5 h-5" />}
            />
            <KpiCard
              title="Tỷ lệ nghỉ phép"
              value={`${report.kpis.leave_rate_pct}%`}
              subtitle={`${report.kpis.leave_days} ngày phép • ${report.kpis.absent_days} ngày vắng`}
              tooltip={report.definitions.leave_days}
              tone="green"
              icon={<Download className="w-5 h-5" />}
            />
            <KpiCard
              title="Cảnh báo bất thường"
              value={report.kpis.total_anomalies}
              subtitle={`${report.kpis.high_anomalies} mức cao • ${report.kpis.open_anomalies} đang mở`}
              tone={report.kpis.high_anomalies > 0 ? 'red' : 'teal'}
              icon={<AlertTriangle className="w-5 h-5" />}
            />
          </div>

          {/* Executive Narrative + Cross-check verification */}
          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-brand-teal" />
                <h3 className="text-sm font-bold text-slate-900">Tóm tắt điều hành (Executive Summary)</h3>
              </div>
              <div className="flex items-center gap-2">
                {report.narrative.verified ? (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-brand-green border border-emerald-200">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Cross-check khớp {report.narrative.checked_count} số liệu SQL
                  </span>
                ) : (
                  <StatusBadge label="Cần rà soát lại số liệu" variant="high" />
                )}
                {report.narrative.used_fallback && (
                  <StatusBadge label="Đã bật mẫu an toàn chống bịa số" variant="info" />
                )}
              </div>
            </div>
            <p className="text-sm text-slate-700 leading-relaxed bg-brand-bg/50 rounded-lg p-4 border border-brand-border/70">
              {report.narrative.text}
            </p>
          </div>

          {/* Department metrics table */}
          <div className="space-y-2.5">
            <h3 className="text-sm font-bold text-slate-900">1. Tổng hợp theo phòng ban</h3>
            <DataTable
              columns={deptColumns}
              data={report.department_metrics}
              rowKey={(r) => r.department_id}
              emptyTitle="Chưa có dữ liệu phòng ban trong kỳ này"
            />
          </div>

          {/* Top late employees */}
          <div className="space-y-2.5">
            <h3 className="text-sm font-bold text-slate-900">2. Danh sách nhân sự cần nhắc nhở giờ giấc (Top đi muộn)</h3>
            <DataTable
              columns={topLateColumns}
              data={report.top_late_employees}
              rowKey={(r) => r.employee_id}
              emptyTitle="Không ghi nhận trường hợp đi muộn trong kỳ"
              emptyDescription="Tất cả nhân sự trong phạm vi đều đi làm đúng giờ."
            />
          </div>

          {/* Anomalies in period */}
          <div className="space-y-2.5">
            <h3 className="text-sm font-bold text-slate-900">3. Cảnh báo bất thường phát hiện trong kỳ ({report.anomalies.length})</h3>
            <DataTable
              columns={anomalyColumns}
              data={report.anomalies}
              rowKey={(r) => String(r.anomaly_id)}
              emptyTitle="Không có cảnh báo bất thường trong kỳ này"
              emptyDescription="Bạn có thể chạy quét lại tại màn hình Cảnh báo bất thường nếu vừa cập nhật dữ liệu mới."
            />
          </div>

          {/* Business rule definitions */}
          <div className="rounded-card border border-blue-200 bg-blue-50/50 p-4 text-xs text-slate-700 space-y-1.5">
            <div className="flex items-center gap-1.5 font-semibold text-brand-navy">
              <Info className="w-4 h-4 text-brand-blue" />
              <span>Quy ước tính toán nghiệp vụ áp dụng trong báo cáo</span>
            </div>
            <ul className="list-disc pl-5 space-y-1 text-slate-600">
              <li>
                <strong>Ca chuẩn:</strong> {report.definitions.standard_shift}
              </li>
              <li>
                <strong>Tỷ lệ đi muộn:</strong> {report.definitions.late_rate_pct}
              </li>
              <li>
                <strong>Số ngày nghỉ phép:</strong> {report.definitions.leave_days}
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
};
