import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  Eye,
  FileSpreadsheet,
  FileUp,
  History,
  Play,
  ShieldAlert,
  Upload,
  X,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiDownload, apiFetch, ApiError } from '../lib/api';
import { KpiCard } from '../components/ui/KpiCard';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

type ImportDataType = 'attendance' | 'employees' | 'leave_requests';

interface RowWarning {
  code: 'missing_punch' | 'weekend_or_holiday' | 'future_date' | string;
  level: 'warning' | 'high' | string;
  label: string;
  detail: string;
}

interface PreviewRowItem extends Record<string, unknown> {
  row_number?: number;
  warnings?: RowWarning[];
  is_future_date?: boolean;
  is_incomplete_punch?: boolean;
}

type DuplicateAction = 'keep_existing' | 'update_from_excel';

interface DuplicateRowItem {
  row_number: number;
  reason: string;
  data: Record<string, unknown>;
  existing?: Record<string, unknown> | null;
  duplicate_source?: 'database' | 'in_file' | string;
  is_identical?: boolean;
  match_type?: 'exact_match' | 'key_conflict' | string;
  changed_fields?: string[];
  comparison_label?: string;
  can_update?: boolean;
  default_action?: DuplicateAction;
}

interface UpdatedRecordAudit {
  row_number: number;
  employee_id: string;
  work_date?: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  updated_by: string;
  updated_at: string;
}

interface ErrorRowItem {
  row_number: number;
  error: string;
  fields?: Record<string, string>;
  raw: Record<string, unknown>;
}

interface PreviewResponse {
  batch_id: string;
  file_name: string;
  data_type: ImportDataType;
  reference_today?: string;
  summary: {
    rows_total: number;
    rows_valid: number;
    rows_warning: number;
    rows_future: number;
    rows_error: number;
    rows_duplicate: number;
  };
  preview_rows: PreviewRowItem[];
  duplicate_rows: DuplicateRowItem[];
  error_rows: ErrorRowItem[];
}

interface ConfirmResult {
  status: string;
  batch_id: string;
  data_type: string;
  inserted: number;
  updated: number;
  skipped: number;
  rejected_future: number;
  errors: number;
  rejected_total: number;
  allow_future_dates: boolean;
  duplicate_decisions?: Record<string, DuplicateAction>;
  updated_records?: UpdatedRecordAudit[];
  anomaly_scan?: {
    periods: string[];
    inserted: number;
    updated: number;
    by_rule: Record<string, number>;
  } | null;
}

interface ImportLogRow {
  id: number;
  batch_id?: string | null;
  file_name: string;
  data_type: string;
  uploaded_by: string;
  uploaded_by_username?: string | null;
  rows_total: number;
  rows_valid: number;
  rows_error: number;
  rows_duplicate: number;
  status: string;
  has_snapshot?: boolean;
  created_at: string;
}

interface ImportLogDetailResponse {
  log: ImportLogRow;
  has_snapshot: boolean;
  can_resume_confirm: boolean;
  can_download_errors: boolean;
  preview: PreviewResponse | null;
  result: (ConfirmResult & {
    duplicate_policy?: string;
    confirmed_at?: string;
    failed_at?: string;
    error?: string;
  }) | null;
}

const DATA_TYPE_META: Record<ImportDataType, { label: string; desc: string }> = {
  attendance: {
    label: 'Dữ liệu chấm công (attendance)',
    desc: 'Cột bắt buộc: employee_id, work_date, check_in, check_out, status',
  },
  employees: {
    label: 'Danh sách nhân viên (employees)',
    desc: 'Cột bắt buộc: employee_id, full_name, department_id, position, start_date, role',
  },
  leave_requests: {
    label: 'Đơn nghỉ phép (leave_requests)',
    desc: 'Cột bắt buộc: employee_id, leave_type, from_date, to_date, reason, status',
  },
};

function shortTime(val: unknown): string {
  if (!val) return 'Trống';
  const s = String(val);
  return s.length >= 19 ? s.slice(11, 19) : s;
}

function buildDefaultDuplicateDecisions(rows: DuplicateRowItem[]): Record<string, DuplicateAction> {
  const initial: Record<string, DuplicateAction> = {};
  rows.forEach((r) => {
    initial[String(r.row_number)] = 'keep_existing';
  });
  return initial;
}

export const ImportPage: React.FC = () => {
  const { showToast, setSelectedPeriod } = useAuth();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [dataType, setDataType] = useState<ImportDataType>('attendance');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState<boolean>(false);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'valid' | 'duplicate' | 'error'>('valid');
  const [duplicateDecisions, setDuplicateDecisions] = useState<Record<string, DuplicateAction>>({});
  const [allowFutureDates, setAllowFutureDates] = useState<boolean>(false);
  const [expandedErrorRows, setExpandedErrorRows] = useState<Record<number, boolean>>({});
  const [confirmOpen, setConfirmOpen] = useState<boolean>(false);
  const [confirming, setConfirming] = useState<boolean>(false);
  const [lastResult, setLastResult] = useState<ConfirmResult | null>(null);

  const [logs, setLogs] = useState<ImportLogRow[]>([]);
  const [loadingLogs, setLoadingLogs] = useState<boolean>(true);
  const [logsError, setLogsError] = useState<string | null>(null);

  const [historyModalOpen, setHistoryModalOpen] = useState<boolean>(false);
  const [historyDetail, setHistoryDetail] = useState<ImportLogDetailResponse | null>(null);
  const [historyLoading, setHistoryLoading] = useState<boolean>(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyTab, setHistoryTab] = useState<'valid' | 'duplicate' | 'error'>('valid');
  const [historyExpandedErrors, setHistoryExpandedErrors] = useState<Record<number, boolean>>({});

  const loadLogs = useCallback(async () => {
    setLoadingLogs(true);
    setLogsError(null);
    try {
      const res = await apiFetch<{ items: ImportLogRow[] }>('/imports/logs');
      setLogs(res.items || []);
    } catch (err) {
      setLogsError(err instanceof ApiError ? err.message : 'Không thể tải lịch sử nhập dữ liệu.');
    } finally {
      setLoadingLogs(false);
    }
  }, []);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const handleDownloadTemplate = async () => {
    try {
      await apiDownload(`/imports/template/${dataType}`, `template_${dataType}.xlsx`);
      showToast(`Đã tải file mẫu template_${dataType}.xlsx`, 'success');
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể tải file mẫu.', 'error');
    }
  };

  const handlePreviewUpload = async () => {
    if (!selectedFile) {
      showToast('Vui lòng chọn tệp .xlsx hoặc .csv trước khi kiểm tra.', 'error');
      return;
    }
    setUploading(true);
    setLastResult(null);
    setAllowFutureDates(false);
    setExpandedErrorRows({});
    try {
      const fd = new FormData();
      fd.append('data_type', dataType);
      fd.append('file', selectedFile);
      const res = await apiFetch<PreviewResponse>('/imports/preview', {
        method: 'POST',
        body: fd,
      });
      setPreview(res);
      setDuplicateDecisions(buildDefaultDuplicateDecisions(res.duplicate_rows || []));
      if (res.summary.rows_valid > 0) {
        setActiveTab('valid');
      } else if (res.summary.rows_error > 0) {
        setActiveTab('error');
      } else {
        setActiveTab('duplicate');
      }
      showToast(
        `Đã kiểm tra ${res.summary.rows_total} dòng từ ${res.file_name} (${res.summary.rows_warning} dòng có cảnh báo nghiệp vụ).`,
        'info'
      );
      loadLogs();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể phân tích file tải lên.', 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleDownloadErrorsForBatch = async (batchId: string) => {
    try {
      await apiDownload(`/imports/errors/${batchId}`, `errors_${batchId}.csv`);
      showToast('Đã tải tệp CSV dòng lỗi (đã vô hiệu hóa ký tự công thức).', 'success');
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể tải danh sách dòng lỗi.', 'error');
    }
  };

  const handleDownloadErrors = async () => {
    if (!preview) return;
    await handleDownloadErrorsForBatch(preview.batch_id);
  };

  const handleViewHistoryDetail = async (logRow: ImportLogRow) => {
    setHistoryModalOpen(true);
    setHistoryLoading(true);
    setHistoryError(null);
    setHistoryDetail(null);
    setHistoryExpandedErrors({});
    try {
      const res = await apiFetch<ImportLogDetailResponse>(`/imports/logs/${logRow.id}`);
      setHistoryDetail(res);
      if (res.preview) {
        if (res.preview.summary.rows_valid > 0) setHistoryTab('valid');
        else if (res.preview.summary.rows_error > 0) setHistoryTab('error');
        else setHistoryTab('duplicate');
      }
    } catch (err) {
      setHistoryError(err instanceof ApiError ? err.message : 'Không thể tải chi tiết phiên nhập dữ liệu.');
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleResumeFromHistory = () => {
    if (!historyDetail?.preview) return;
    const restored = historyDetail.preview;
    setDataType(restored.data_type);
    setPreview(restored);
    setDuplicateDecisions(buildDefaultDuplicateDecisions(restored.duplicate_rows || []));
    setLastResult(null);
    setAllowFutureDates(false);
    setExpandedErrorRows({});
    if (restored.summary.rows_valid > 0) setActiveTab('valid');
    else if (restored.summary.rows_error > 0) setActiveTab('error');
    else setActiveTab('duplicate');
    setHistoryModalOpen(false);
    showToast(`Đã mở lại phiên ${restored.batch_id} — bạn có thể rà soát và xác nhận nhập ngay.`, 'info');
    if (typeof window !== 'undefined' && typeof window.scrollTo === 'function') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const setRowDuplicateDecision = (rowNumber: number, action: DuplicateAction) => {
    setDuplicateDecisions((prev) => ({
      ...prev,
      [String(rowNumber)]: action,
    }));
  };

  const applyDuplicatePreset = (mode: 'keep_all' | 'update_conflicts') => {
    if (!preview) return;
    const next: Record<string, DuplicateAction> = {};
    preview.duplicate_rows.forEach((r) => {
      const canUpdate = r.can_update !== false && r.duplicate_source !== 'in_file';
      if (mode === 'update_conflicts' && canUpdate && !r.is_identical) {
        next[String(r.row_number)] = 'update_from_excel';
      } else {
        next[String(r.row_number)] = 'keep_existing';
      }
    });
    setDuplicateDecisions(next);
  };

  const handleConfirmImport = async () => {
    if (!preview) return;
    setConfirming(true);
    try {
      const hasAnyUpdate = Object.values(duplicateDecisions).some((v) => v === 'update_from_excel');
      const res = await apiFetch<ConfirmResult>(`/imports/confirm/${preview.batch_id}`, {
        method: 'POST',
        body: JSON.stringify({
          duplicate_policy: hasAnyUpdate ? 'update' : 'skip',
          duplicate_decisions: duplicateDecisions,
          allow_future_dates: allowFutureDates,
        }),
      });
      setLastResult(res);
      setPreview(null);
      setDuplicateDecisions({});
      setSelectedFile(null);
      setAllowFutureDates(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
      setConfirmOpen(false);
      showToast(
        `Hoàn tất: thêm mới ${res.inserted}, cập nhật ${res.updated}, bỏ qua ${res.skipped}, từ chối ${res.rejected_total}.`,
        'success'
      );
      loadLogs();
    } catch (err) {
      setConfirmOpen(false);
      showToast(err instanceof ApiError ? err.message : 'Xác nhận nhập dữ liệu thất bại.', 'error');
      loadLogs();
    } finally {
      setConfirming(false);
    }
  };

  const logColumns: ColumnDef<ImportLogRow>[] = [
    { key: 'created_at', header: 'Thời điểm' },
    { key: 'file_name', header: 'Tên tệp', render: (r) => <span className="font-medium text-slate-900">{r.file_name}</span> },
    { key: 'data_type', header: 'Loại dữ liệu', render: (r) => <StatusBadge label={r.data_type} variant="info" /> },
    { key: 'uploaded_by_username', header: 'Người thực hiện', render: (r) => r.uploaded_by_username || r.uploaded_by },
    { key: 'rows_total', header: 'Tổng' },
    { key: 'rows_valid', header: 'Đủ ĐK nhập', render: (r) => <span className="text-brand-green font-semibold">{r.rows_valid}</span> },
    { key: 'rows_duplicate', header: 'Trùng', render: (r) => <span className="text-brand-amber font-semibold">{r.rows_duplicate}</span> },
    { key: 'rows_error', header: 'Lỗi', render: (r) => <span className="text-brand-red font-semibold">{r.rows_error}</span> },
    {
      key: 'status',
      header: 'Trạng thái',
      render: (r) => (
        <StatusBadge
          label={r.status === 'completed' ? 'Hoàn tất' : r.status === 'failed' ? 'Thất bại' : 'Xem trước'}
          variant={r.status === 'completed' ? 'approved' : r.status === 'failed' ? 'rejected' : 'pending'}
        />
      ),
    },
    {
      key: 'actions',
      header: 'Thao tác',
      render: (r) => (
        <button
          type="button"
          onClick={() => handleViewHistoryDetail(r)}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-brand-border bg-white text-xs font-semibold text-brand-blue hover:bg-blue-50"
        >
          <Eye className="w-3.5 h-3.5" />
          Xem lại
        </button>
      ),
    },
  ];

  // Build structured columns for "Dòng đủ điều kiện nhập" WITH inline business warnings!
  const buildValidColumns = (target: PreviewResponse | null = preview): ColumnDef<PreviewRowItem>[] => {
    if (!target) return [];
    if (target.data_type === 'attendance') {
      return [
        { key: 'row_number', header: 'Dòng', render: (r) => <span className="font-mono text-slate-500">{r.row_number ?? '—'}</span> },
        { key: 'employee_id', header: 'Mã NV', render: (r) => <span className="font-mono font-semibold text-brand-navy">{String(r.employee_id ?? '')}</span> },
        { key: 'work_date', header: 'Ngày', render: (r) => <span className="font-mono">{String(r.work_date ?? '')}</span> },
        { key: 'check_in', header: 'Giờ vào', render: (r) => <span className="font-mono">{shortTime(r.check_in)}</span> },
        {
          key: 'check_out',
          header: 'Giờ ra',
          render: (r) =>
            r.check_out ? (
              <span className="font-mono">{shortTime(r.check_out)}</span>
            ) : (
              <span className="font-semibold text-brand-amber">Trống</span>
            ),
        },
        { key: 'status', header: 'Trạng thái', render: (r) => <StatusBadge label={String(r.status ?? '')} variant="info" /> },
        {
          key: 'warnings',
          header: 'Cảnh báo nghiệp vụ',
          render: (r) => {
            const ws = r.warnings ?? [];
            if (ws.length === 0) {
              return <StatusBadge label="Bình thường" variant="approved" />;
            }
            return (
              <div className="flex flex-wrap gap-1.5 max-w-md whitespace-normal">
                {ws.map((w, idx) => (
                  <span
                    key={`${w.code}-${idx}`}
                    title={w.detail}
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                      w.code === 'future_date'
                        ? 'bg-red-50 text-brand-red border-red-200'
                        : 'bg-amber-50 text-brand-amber border-amber-200'
                    }`}
                  >
                    <AlertTriangle className="w-3 h-3 shrink-0" />
                    {w.label}
                  </span>
                ))}
              </div>
            );
          },
        },
      ];
    }

    if (target.preview_rows.length === 0) return [];
    const hiddenKeys = new Set(['warnings', 'is_future_date', 'is_incomplete_punch']);
    return Object.keys(target.preview_rows[0])
      .filter((k) => !hiddenKeys.has(k))
      .map((k) => ({
        key: k,
        header: k,
        render: (row) => String(row[k] ?? '—'),
      }));
  };

  // Build 9-column side-by-side comparison & per-row resolution table for Duplicate tab
  const buildDuplicateColumns = (
    target: PreviewResponse | null = preview,
    interactive = true,
    appliedDecisions?: Record<string, DuplicateAction>
  ): ColumnDef<DuplicateRowItem>[] => {
    if (!target) return [];

    const renderActionCell = (r: DuplicateRowItem) => {
      const rowKeyStr = String(r.row_number);
      const canUpdate = r.can_update !== false && r.duplicate_source !== 'in_file' && target.data_type !== 'leave_requests';

      if (!interactive) {
        const applied = appliedDecisions?.[rowKeyStr];
        if (!applied) {
          return <span className="text-[11px] text-slate-400">Chưa xác nhận</span>;
        }
        return (
          <StatusBadge
            label={applied === 'update_from_excel' ? 'Đã cập nhật bằng Excel' : 'Đã giữ dữ liệu hiện tại'}
            variant={applied === 'update_from_excel' ? 'medium' : 'dismissed'}
          />
        );
      }

      if (!canUpdate) {
        return (
          <div className="space-y-0.5">
            <StatusBadge label="Giữ dữ liệu hiện tại" variant="dismissed" />
            <p className="text-[10px] text-slate-400 whitespace-normal max-w-[170px]">
              {r.duplicate_source === 'in_file'
                ? 'Trùng nội bộ trong file Excel'
                : 'Không hỗ trợ ghi đè loại dữ liệu này'}
            </p>
          </div>
        );
      }

      const selectedAction: DuplicateAction = duplicateDecisions[rowKeyStr] ?? 'keep_existing';
      return (
        <div
          className="inline-flex flex-col gap-1 min-w-[168px]"
          role="radiogroup"
          aria-label={`Hành động xử lý dòng ${r.row_number}`}
        >
          <label
            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] font-medium cursor-pointer transition-colors ${
              selectedAction === 'keep_existing'
                ? 'border-brand-navy bg-slate-100 text-brand-navy font-semibold'
                : 'border-brand-border bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            <input
              type="radio"
              name={`dup-action-${r.row_number}`}
              value="keep_existing"
              checked={selectedAction === 'keep_existing'}
              onChange={() => setRowDuplicateDecision(r.row_number, 'keep_existing')}
              className="accent-brand-navy"
            />
            <span>Giữ dữ liệu hiện tại</span>
          </label>
          <label
            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] font-medium cursor-pointer transition-colors ${
              selectedAction === 'update_from_excel'
                ? 'border-brand-blue bg-blue-50 text-brand-blue font-semibold'
                : 'border-brand-border bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            <input
              type="radio"
              name={`dup-action-${r.row_number}`}
              value="update_from_excel"
              checked={selectedAction === 'update_from_excel'}
              onChange={() => setRowDuplicateDecision(r.row_number, 'update_from_excel')}
              className="accent-brand-blue"
            />
            <span>Cập nhật bằng Excel</span>
          </label>
        </div>
      );
    };

    if (target.data_type === 'attendance') {
      return [
        {
          key: 'row_number',
          header: 'Dòng Excel',
          render: (r) => <span className="font-mono text-slate-500">{r.row_number}</span>,
        },
        {
          key: 'employee_id',
          header: 'Mã nhân viên',
          render: (r) => <span className="font-mono font-semibold text-brand-navy">{String(r.data.employee_id ?? '')}</span>,
        },
        {
          key: 'work_date',
          header: 'Ngày chấm công',
          render: (r) => <span className="font-mono">{String(r.data.work_date ?? '')}</span>,
        },
        {
          key: 'excel_check_in',
          header: 'Giờ vào (Excel)',
          render: (r) => {
            const diff = (r.changed_fields || []).includes('check_in');
            return (
              <span className={`font-mono ${diff ? 'font-bold text-brand-blue bg-blue-50 px-1.5 py-0.5 rounded' : 'text-slate-800'}`}>
                {shortTime(r.data.check_in)}
              </span>
            );
          },
        },
        {
          key: 'excel_check_out',
          header: 'Giờ ra (Excel)',
          render: (r) => {
            const diff = (r.changed_fields || []).includes('check_out');
            return (
              <span className={`font-mono ${diff ? 'font-bold text-brand-blue bg-blue-50 px-1.5 py-0.5 rounded' : 'text-slate-800'}`}>
                {shortTime(r.data.check_out)}
              </span>
            );
          },
        },
        {
          key: 'db_check_in',
          header: 'Giờ vào (Database)',
          render: (r) => (
            <span className="font-mono text-slate-600">
              {r.existing ? shortTime(r.existing.check_in) : '—'}
            </span>
          ),
        },
        {
          key: 'db_check_out',
          header: 'Giờ ra (Database)',
          render: (r) => (
            <span className="font-mono text-slate-600">
              {r.existing ? shortTime(r.existing.check_out) : '—'}
            </span>
          ),
        },
        {
          key: 'comparison',
          header: 'Kết quả đối chiếu',
          render: (r) => {
            const statusDiff = (r.changed_fields || []).includes('status');
            const label =
              r.comparison_label ||
              (r.duplicate_source === 'in_file'
                ? 'Trùng lặp trong file Excel'
                : r.is_identical
                  ? 'Trùng hoàn toàn'
                  : 'Trùng khóa, khác dữ liệu');
            return (
              <div className="space-y-1">
                <StatusBadge
                  label={label}
                  variant={r.is_identical ? 'dismissed' : 'medium'}
                />
                {statusDiff && (
                  <p className="text-[10px] text-amber-800 whitespace-normal">
                    Trạng thái: Excel <strong>{String(r.data.status ?? '')}</strong> vs DB{' '}
                    <strong>{String(r.existing?.status ?? '')}</strong>
                  </p>
                )}
              </div>
            );
          },
        },
        {
          key: 'resolution',
          header: 'Hành động xử lý',
          render: renderActionCell,
        },
      ];
    }

    return [
      { key: 'row_number', header: 'Dòng Excel' },
      { key: 'reason', header: 'Lý do trùng lặp' },
      {
        key: 'data',
        header: 'Dữ liệu trong file',
        render: (r) => <span className="font-mono text-[11px] text-slate-700 whitespace-normal block max-w-xs">{JSON.stringify(r.data)}</span>,
      },
      {
        key: 'existing',
        header: 'Bản ghi trong hệ thống',
        render: (r) => (
          <span className="font-mono text-[11px] text-slate-500 whitespace-normal block max-w-xs">
            {r.existing ? JSON.stringify(r.existing) : 'Trùng trong file'}
          </span>
        ),
      },
      {
        key: 'comparison',
        header: 'Kết quả đối chiếu',
        render: (r) => (
          <StatusBadge
            label={r.comparison_label || (r.is_identical ? 'Trùng hoàn toàn' : 'Trùng khóa, khác dữ liệu')}
            variant={r.is_identical ? 'dismissed' : 'medium'}
          />
        ),
      },
      {
        key: 'resolution',
        header: 'Hành động xử lý',
        render: renderActionCell,
      },
    ];
  };

  // Build structured tabular columns for Error tab + expandable raw JSON!
  const buildErrorColumns = (
    target: PreviewResponse | null = preview,
    expandedMap: Record<number, boolean> = expandedErrorRows,
    setExpandedMap: React.Dispatch<React.SetStateAction<Record<number, boolean>>> = setExpandedErrorRows
  ): ColumnDef<ErrorRowItem>[] => {
    if (!target) return [];
    const baseCols: ColumnDef<ErrorRowItem>[] = [{ key: 'row_number', header: 'Dòng' }];
    if (target.data_type === 'attendance') {
      baseCols.push(
        { key: 'emp', header: 'Mã NV', render: (r) => <span className="font-mono font-semibold">{r.fields?.employee_id || '—'}</span> },
        { key: 'date', header: 'Ngày', render: (r) => <span className="font-mono">{r.fields?.work_date || '—'}</span> },
        { key: 'ci', header: 'Giờ vào', render: (r) => <span className="font-mono text-[11px]">{r.fields?.check_in || 'Trống'}</span> },
        { key: 'co', header: 'Giờ ra', render: (r) => <span className="font-mono text-[11px]">{r.fields?.check_out || 'Trống'}</span> }
      );
    } else if (target.data_type === 'employees') {
      baseCols.push(
        { key: 'emp', header: 'Mã NV', render: (r) => <span className="font-mono font-semibold">{r.fields?.employee_id || '—'}</span> },
        { key: 'name', header: 'Họ tên', render: (r) => r.fields?.full_name || '—' },
        { key: 'dept', header: 'Phòng ban', render: (r) => r.fields?.department_id || '—' }
      );
    } else {
      baseCols.push(
        { key: 'emp', header: 'Mã NV', render: (r) => <span className="font-mono font-semibold">{r.fields?.employee_id || '—'}</span> },
        { key: 'from', header: 'Từ ngày', render: (r) => r.fields?.from_date || '—' },
        { key: 'to', header: 'Đến ngày', render: (r) => r.fields?.to_date || '—' }
      );
    }

    baseCols.push(
      {
        key: 'error',
        header: 'Lý do lỗi',
        render: (r) => <span className="text-brand-red font-medium whitespace-normal block max-w-xs">{r.error}</span>,
      },
      {
        key: 'raw_toggle',
        header: 'Chi tiết',
        render: (r) => {
          const isOpen = Boolean(expandedMap[r.row_number]);
          return (
            <div className="space-y-1.5">
              <button
                type="button"
                onClick={() =>
                  setExpandedMap((prev) => ({
                    ...prev,
                    [r.row_number]: !prev[r.row_number],
                  }))
                }
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-blue hover:underline"
              >
                {isOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                {isOpen ? 'Ẩn JSON' : 'Xem JSON'}
              </button>
              {isOpen && (
                <pre className="p-2 rounded bg-slate-100 border border-brand-border text-[10px] text-slate-600 max-w-xs overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(r.raw, null, 2)}
                </pre>
              )}
            </div>
          );
        },
      }
    );
    return baseCols;
  };

  // Dynamic effective counts reflecting HR's per-row duplicate decisions & future-date guard
  const effectiveInsertCount = preview
    ? Math.max(
        0,
        preview.summary.rows_valid - (allowFutureDates ? 0 : preview.summary.rows_future)
      )
    : 0;

  let effectiveUpdateCount = 0;
  let effectiveSkipCount = 0;
  let dupFutureBlockedCount = 0;
  if (preview) {
    for (const dup of preview.duplicate_rows) {
      const canUpdate = dup.can_update !== false && dup.duplicate_source !== 'in_file' && preview.data_type !== 'leave_requests';
      const decision = canUpdate ? duplicateDecisions[String(dup.row_number)] ?? 'keep_existing' : 'keep_existing';
      if (decision === 'update_from_excel') {
        if (Boolean(dup.data?.is_future_date) && !allowFutureDates) {
          dupFutureBlockedCount += 1;
        } else {
          effectiveUpdateCount += 1;
        }
      } else {
        effectiveSkipCount += 1;
      }
    }
  }
  const effectiveFutureBlockedCount =
    (preview && !allowFutureDates ? preview.summary.rows_future : 0) + dupFutureBlockedCount;

  const buildConfirmButtonLabel = (): string => {
    const parts: string[] = [];
    if (effectiveInsertCount > 0) parts.push(`${effectiveInsertCount} thêm mới`);
    if (effectiveUpdateCount > 0) parts.push(`${effectiveUpdateCount} cập nhật`);
    if (parts.length === 0) return 'Xác nhận nhập (0 dòng)';
    return `Xác nhận nhập (${parts.join(', ')})`;
  };

  return (
    <div className="space-y-6">
      {/* Step 1 & 2: Choose data type + download template + upload */}
      <div className="rounded-card border border-brand-border bg-white p-6 shadow-sm space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              Nhập dữ liệu từ Excel / CSV (Staging, Cảnh báo Nghiệp vụ &amp; Rollback)
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Hệ thống tách bạch lỗi cấu trúc (chặn nhập), cảnh báo nghiệp vụ (thiếu giờ ra, chấm công cuối tuần chưa có OT) và bảo vệ ngày tương lai trước khi ghi CSDL.
            </p>
          </div>
          <button
            type="button"
            onClick={handleDownloadTemplate}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg border border-brand-border bg-slate-50 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            <Download className="w-4 h-4 text-brand-teal" />
            Tải file mẫu (.xlsx)
          </button>
        </div>

        {/* Data type selection */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {(Object.keys(DATA_TYPE_META) as ImportDataType[]).map((key) => {
            const active = dataType === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setDataType(key);
                  setPreview(null);
                  setLastResult(null);
                }}
                className={`text-left p-3.5 rounded-xl border transition-all ${
                  active
                    ? 'border-brand-blue bg-blue-50/50 ring-2 ring-brand-blue/15'
                    : 'border-brand-border hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className={`w-4 h-4 ${active ? 'text-brand-blue' : 'text-slate-400'}`} />
                  <span className="text-xs font-bold text-slate-900">{DATA_TYPE_META[key].label}</span>
                </div>
                <p className="mt-1.5 text-[11px] text-slate-500 leading-relaxed">{DATA_TYPE_META[key].desc}</p>
              </button>
            );
          })}
        </div>

        {/* Upload dropzone */}
        <div className="rounded-xl border-2 border-dashed border-slate-300 bg-brand-bg/40 p-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <div className="w-11 h-11 rounded-xl bg-white border border-brand-border flex items-center justify-center text-brand-blue shadow-sm shrink-0">
              <FileUp className="w-5 h-5" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-900">
                {selectedFile ? selectedFile.name : 'Chọn tệp dữ liệu (.xlsx hoặc .csv, tối đa 5 MB)'}
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                {selectedFile
                  ? `Dung lượng: ${(selectedFile.size / 1024).toFixed(1)} KB — Sẵn sàng kiểm tra`
                  : 'Bước 1: Chọn file → Bước 2: Kiểm tra cấu trúc & cảnh báo nghiệp vụ → Bước 3: Xác nhận nhập.'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => {
                setSelectedFile(e.target.files?.[0] || null);
                setPreview(null);
                setLastResult(null);
              }}
              className="hidden"
              id="import-file-input"
            />
            <label
              htmlFor="import-file-input"
              className="cursor-pointer px-3.5 py-2 rounded-lg border border-brand-border bg-white text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              Chọn tệp...
            </label>
            <button
              type="button"
              disabled={!selectedFile || uploading}
              onClick={handlePreviewUpload}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
            >
              <Upload className="w-4 h-4" />
              {uploading ? 'Đang kiểm tra...' : 'Kiểm tra & Xem trước'}
            </button>
          </div>
        </div>
      </div>

      {/* Detailed Post-Confirm Summary Banner (P2: rõ thực nhập, bỏ qua, từ chối + quét R1–R8) */}
      {lastResult && (
        <div className="rounded-card border border-emerald-200 bg-emerald-50/70 p-5 space-y-3 text-xs text-emerald-950">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="w-5 h-5 text-brand-green shrink-0" />
              <div>
                <p className="font-bold text-sm">Đã hoàn tất nhập dữ liệu phiên {lastResult.batch_id}</p>
                <p className="text-[11px] text-emerald-800">
                  Kết quả ghi nhận thực tế vào cơ sở dữ liệu (đã bảo vệ atomic transaction):
                </p>
              </div>
            </div>
            <StatusBadge label="Hoàn tất" variant="approved" />
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div className="rounded-lg bg-white border border-emerald-200 p-2.5">
              <p className="text-[11px] text-slate-500">Thực nhập thành công</p>
              <p className="text-base font-bold text-brand-green">
                {lastResult.inserted + lastResult.updated} dòng
              </p>
              <p className="text-[10px] text-slate-500">
                {lastResult.inserted} thêm mới · {lastResult.updated} cập nhật
              </p>
            </div>
            <div className="rounded-lg bg-white border border-amber-200 p-2.5">
              <p className="text-[11px] text-slate-500">Bỏ qua (trùng khóa)</p>
              <p className="text-base font-bold text-brand-amber">{lastResult.skipped} dòng</p>
              <p className="text-[10px] text-slate-500">Giữ nguyên bản ghi cũ</p>
            </div>
            <div className="rounded-lg bg-white border border-red-200 p-2.5">
              <p className="text-[11px] text-slate-500">Từ chối (ngày tương lai)</p>
              <p className="text-base font-bold text-brand-red">{lastResult.rejected_future} dòng</p>
              <p className="text-[10px] text-slate-500">
                {lastResult.allow_future_dates ? 'Đã cho phép mô phỏng' : 'Đã chặn bảo vệ'}
              </p>
            </div>
            <div className="rounded-lg bg-white border border-red-200 p-2.5">
              <p className="text-[11px] text-slate-500">Từ chối (lỗi cấu trúc)</p>
              <p className="text-base font-bold text-brand-red">{lastResult.errors} dòng</p>
              <p className="text-[10px] text-slate-500">Không ghi vào DB</p>
            </div>
          </div>

          {lastResult.updated_records && lastResult.updated_records.length > 0 && (
            <div className="rounded-lg bg-white border border-blue-200 p-3 space-y-2 text-slate-800">
              <p className="font-bold text-xs text-brand-navy">
                Nhật ký cập nhật bản ghi trùng ({lastResult.updated_records.length} bản ghi — đã lưu audit log trước &amp; sau):
              </p>
              <div className="space-y-1.5 max-h-40 overflow-y-auto">
                {lastResult.updated_records.map((rec) => (
                  <div
                    key={`${rec.row_number}-${rec.employee_id}-${rec.work_date ?? ''}`}
                    className="rounded border border-slate-200 bg-slate-50/70 px-2.5 py-1.5 text-[11px] font-mono flex flex-wrap items-center justify-between gap-2"
                  >
                    <span className="font-semibold text-brand-navy">
                      Dòng {rec.row_number} · {rec.employee_id}
                      {rec.work_date ? ` (${rec.work_date})` : ''}
                    </span>
                    <span className="text-slate-600">
                      Trước: {shortTime(rec.before.check_in)}–{shortTime(rec.before.check_out)} ({String(rec.before.status ?? '')})
                      {' → '}
                      <strong className="text-brand-blue">
                        Sau: {shortTime(rec.after.check_in)}–{shortTime(rec.after.check_out)} ({String(rec.after.status ?? '')})
                      </strong>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {lastResult.anomaly_scan && (
            <div className="rounded-lg bg-white/90 border border-blue-200 px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2 text-slate-800">
              <div className="flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-brand-blue shrink-0" />
                <span>
                  Đã tự động quét lại quy tắc <strong>R1–R8</strong> cho kỳ{' '}
                  <strong>{lastResult.anomaly_scan.periods.join(', ')}</strong>: phát sinh{' '}
                  <strong className="text-brand-blue">{lastResult.anomaly_scan.inserted} cảnh báo mới</strong>{' '}
                  (R2: {lastResult.anomaly_scan.by_rule.R2 ?? 0}, R7: {lastResult.anomaly_scan.by_rule.R7 ?? 0}).
                </span>
              </div>
              <button
                type="button"
                onClick={() => {
                  const targetP = lastResult.anomaly_scan?.periods[0];
                  if (targetP) setSelectedPeriod(targetP);
                  navigate('/anomalies');
                }}
                className="px-3 py-1.5 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700"
              >
                Xem cảnh báo vừa phát hiện →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Step 3 & 4: Preview Staging Results with 5 KPI Cards */}
      {preview && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
            <KpiCard
              title="Tổng số dòng"
              value={preview.summary.rows_total}
              subtitle="Đã đọc từ tệp"
              tone="blue"
              icon={<FileSpreadsheet className="w-5 h-5" />}
            />
            <KpiCard
              title="Dòng đủ điều kiện nhập"
              value={preview.summary.rows_valid}
              subtitle="Hợp lệ về cấu trúc"
              tone="green"
              icon={<CheckCircle2 className="w-5 h-5" />}
            />
            <KpiCard
              title="Dòng có cảnh báo nghiệp vụ"
              value={preview.summary.rows_warning}
              subtitle={
                preview.summary.rows_future > 0
                  ? `Gồm ${preview.summary.rows_future} dòng ngày tương lai`
                  : 'Thiếu CC / Cuối tuần chưa OT'
              }
              tone="amber"
              icon={<AlertCircle className="w-5 h-5" />}
            />
            <KpiCard
              title="Dòng trùng"
              value={preview.summary.rows_duplicate}
              subtitle="Đã tồn tại trong DB"
              tone="teal"
              icon={<Copy className="w-5 h-5" />}
            />
            <KpiCard
              title="Dòng lỗi cần sửa"
              value={preview.summary.rows_error}
              subtitle="Bị chặn không cho nhập"
              tone="red"
              icon={<AlertTriangle className="w-5 h-5" />}
            />
          </div>

          {/* Dedicated Future-Date Guard Banner when future rows exist */}
          {preview.summary.rows_future > 0 && (
            <div className="rounded-card border border-red-200 bg-red-50/70 p-4 flex flex-wrap items-center justify-between gap-3 text-xs text-red-950">
              <div className="flex items-start gap-2.5 max-w-2xl">
                <CalendarClock className="w-5 h-5 text-brand-red shrink-0 mt-0.5" />
                <div>
                  <p className="font-bold">
                    Phát hiện {preview.summary.rows_future} bản ghi có ngày chấm công trong tương lai (lớn hơn {preview.reference_today})
                  </p>
                  <p className="mt-0.5 text-red-800 leading-relaxed">
                    Theo nghiệp vụ chấm công thực tế, bản ghi ngày tương lai được <strong>chặn mặc định</strong> khi xác nhận. Chỉ bật tùy chọn bên cạnh nếu bạn đang nhập dữ liệu mô phỏng / kịch bản kiểm thử.
                  </p>
                </div>
              </div>
              <label className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-red-200 cursor-pointer font-semibold text-brand-red shrink-0">
                <input
                  type="checkbox"
                  checked={allowFutureDates}
                  onChange={(e) => setAllowFutureDates(e.target.checked)}
                />
                Cho phép nhập ngày tương lai (mô phỏng)
              </label>
            </div>
          )}

          {/* Business warning explanation note */}
          {preview.summary.rows_warning > 0 && preview.data_type === 'attendance' && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-2.5 text-xs text-amber-950 leading-relaxed">
              <strong>Lưu ý cảnh báo nghiệp vụ:</strong> Các dòng thiếu giờ ra được phép nhập ở trạng thái <em>chấm công chưa đầy đủ</em> (không tính đủ giờ công và sẽ kích hoạt rà soát <strong>R2</strong>). Các dòng chấm công thứ Bảy/Chủ nhật khi chưa có đơn trong <code>overtime_requests</code> sẽ được đối chiếu bằng quy tắc <strong>R7</strong> sau khi xác nhận nhập.
            </div>
          )}

          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab('valid')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                    activeTab === 'valid' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  Đủ điều kiện nhập ({preview.summary.rows_valid})
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('duplicate')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                    activeTab === 'duplicate' ? 'bg-brand-amber text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  Trùng lặp ({preview.summary.rows_duplicate})
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('error')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                    activeTab === 'error' ? 'bg-brand-red text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  Lỗi cần sửa ({preview.summary.rows_error})
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                {preview.summary.rows_error > 0 && (
                  <button
                    type="button"
                    onClick={handleDownloadErrors}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-200 bg-red-50 text-xs font-semibold text-brand-red hover:bg-red-100"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Tải CSV dòng lỗi
                  </button>
                )}

                <button
                  type="button"
                  disabled={effectiveInsertCount === 0 && effectiveUpdateCount === 0}
                  onClick={() => setConfirmOpen(true)}
                  className="px-4 py-2 rounded-lg bg-brand-green text-white text-xs font-semibold hover:bg-emerald-800 disabled:opacity-50"
                >
                  {buildConfirmButtonLabel()}
                </button>
              </div>
            </div>

            {/* Dynamic Pre-Confirm Summary Bar */}
            <div className="rounded-lg border border-brand-border bg-slate-50/80 px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="font-semibold text-slate-700">Tổng hợp dự kiến trước khi xác nhận:</span>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-brand-green font-semibold">
                  Thêm mới: <strong>{effectiveInsertCount}</strong>
                </span>
                <span className="text-brand-blue font-semibold">
                  Cập nhật: <strong>{effectiveUpdateCount}</strong>
                </span>
                <span className="text-brand-amber font-semibold">
                  Bỏ qua: <strong>{effectiveSkipCount}</strong>
                </span>
                {effectiveFutureBlockedCount > 0 && (
                  <span className="text-brand-red font-semibold">
                    Chặn tương lai: <strong>{effectiveFutureBlockedCount}</strong>
                  </span>
                )}
                <span className="text-brand-red font-semibold">
                  Lỗi không nhập: <strong>{preview.summary.rows_error}</strong>
                </span>
              </div>
            </div>

            {activeTab === 'valid' && (
              <DataTable
                columns={buildValidColumns()}
                data={preview.preview_rows}
                rowKey={(r, i) => `valid-${r.row_number ?? i}`}
                emptyTitle="Không có dòng đủ điều kiện nhập mới"
              />
            )}

            {activeTab === 'duplicate' && (
              <div className="space-y-3">
                {preview.duplicate_rows.length > 0 && (
                  <div className="rounded-lg border border-blue-200 bg-blue-50/60 px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-800">
                    <p className="leading-relaxed">
                      <strong>Bảo vệ dữ liệu trùng khóa:</strong> Hệ thống mặc định chọn{' '}
                      <strong>Giữ dữ liệu hiện tại</strong> cho từng bản ghi. HR có thể đối chiếu từng dòng và chọn{' '}
                      <strong>Cập nhật bằng Excel</strong> nếu muốn ghi đè có kiểm soát (có kiểm tra đồng thời &amp; lưu nhật ký trước/sau).
                    </p>
                    {preview.data_type !== 'leave_requests' && (
                      <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                        <button
                          type="button"
                          onClick={() => applyDuplicatePreset('keep_all')}
                          className="px-2.5 py-1 rounded-md border border-brand-border bg-white text-[11px] font-semibold text-slate-700 hover:bg-slate-100"
                        >
                          Giữ tất cả hiện tại
                        </button>
                        <button
                          type="button"
                          onClick={() => applyDuplicatePreset('update_conflicts')}
                          className="px-2.5 py-1 rounded-md border border-blue-200 bg-white text-[11px] font-semibold text-brand-blue hover:bg-blue-50"
                        >
                          Chọn cập nhật dòng khác dữ liệu
                        </button>
                      </div>
                    )}
                  </div>
                )}
                <DataTable
                  columns={buildDuplicateColumns(preview, true)}
                  data={preview.duplicate_rows}
                  rowKey={(r) => `dup-${r.row_number}`}
                  emptyTitle="Không có dòng trùng lặp"
                />
              </div>
            )}

            {activeTab === 'error' && (
              <DataTable
                columns={buildErrorColumns()}
                data={preview.error_rows}
                rowKey={(r) => `err-${r.row_number}`}
                emptyTitle="Không phát hiện lỗi cấu trúc dữ liệu"
              />
            )}
          </div>
        </div>
      )}

      {/* Step 5: History Logs */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-brand-navy" />
          <h3 className="text-sm font-bold text-slate-900">Lịch sử nhập dữ liệu gần đây</h3>
        </div>
        {loadingLogs && <LoadingSkeleton rows={3} />}
        {!loadingLogs && logsError && <ErrorState message={logsError} onRetry={loadLogs} />}
        {!loadingLogs && !logsError && (
          <DataTable
            columns={logColumns}
            data={logs}
            rowKey={(r) => String(r.id)}
            emptyTitle="Chưa có lịch sử nhập dữ liệu nào"
            emptyDescription="Các lần kiểm tra và xác nhận import từ Excel/CSV sẽ được ghi nhận đầy đủ tại đây."
          />
        )}
      </div>

      {/* History Detail Modal (Xem lại chi tiết phiên nhập & Mở lại để xác nhận) */}
      {historyModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Chi tiết lịch sử nhập dữ liệu"
        >
          <div className="w-full max-w-5xl max-h-[88vh] flex flex-col rounded-card border border-brand-border bg-white shadow-xl overflow-hidden">
            {/* Modal Header */}
            <div className="px-5 py-4 border-b border-brand-border flex items-start justify-between gap-3 bg-slate-50/70">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <History className="w-4 h-4 text-brand-navy shrink-0" />
                  <h3 className="text-sm font-bold text-slate-900 truncate">
                    {historyDetail ? `Chi tiết phiên nhập: ${historyDetail.log.file_name}` : 'Chi tiết lịch sử nhập dữ liệu'}
                  </h3>
                  {historyDetail && (
                    <StatusBadge
                      label={
                        historyDetail.log.status === 'completed'
                          ? 'Hoàn tất'
                          : historyDetail.log.status === 'failed'
                            ? 'Thất bại'
                            : 'Xem trước'
                      }
                      variant={
                        historyDetail.log.status === 'completed'
                          ? 'approved'
                          : historyDetail.log.status === 'failed'
                            ? 'rejected'
                            : 'pending'
                      }
                    />
                  )}
                </div>
                {historyDetail && (
                  <p className="mt-1 text-[11px] text-slate-500">
                    Mã phiên: <span className="font-mono font-semibold text-slate-700">{historyDetail.log.batch_id || `#${historyDetail.log.id}`}</span>
                    {' · '}Loại: <span className="font-semibold text-slate-700">{historyDetail.log.data_type}</span>
                    {' · '}Người thực hiện: <span className="font-semibold text-slate-700">{historyDetail.log.uploaded_by_username || historyDetail.log.uploaded_by}</span>
                    {' · '}Thời điểm: <span className="font-mono">{historyDetail.log.created_at}</span>
                  </p>
                )}
              </div>
              <button
                type="button"
                aria-label="Đóng chi tiết lịch sử"
                onClick={() => setHistoryModalOpen(false)}
                className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-200/70 hover:text-slate-900"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto space-y-4 text-xs">
              {historyLoading && <LoadingSkeleton rows={4} />}
              {!historyLoading && historyError && <ErrorState message={historyError} />}

              {!historyLoading && !historyError && historyDetail && (
                <>
                  {/* Confirm Result Summary (if completed) */}
                  {historyDetail.log.status === 'completed' && historyDetail.result && (
                    <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-bold text-emerald-950">Kết quả đã ghi nhận vào cơ sở dữ liệu</p>
                        {historyDetail.result.confirmed_at && (
                          <span className="text-[11px] font-mono text-emerald-800">
                            Xác nhận lúc: {historyDetail.result.confirmed_at}
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                        <div className="rounded-lg bg-white border border-emerald-200 p-2.5">
                          <p className="text-[11px] text-slate-500">Thực nhập thành công</p>
                          <p className="text-sm font-bold text-brand-green">
                            {historyDetail.result.inserted + historyDetail.result.updated} dòng
                          </p>
                          <p className="text-[10px] text-slate-500">
                            {historyDetail.result.inserted} mới · {historyDetail.result.updated} cập nhật
                          </p>
                        </div>
                        <div className="rounded-lg bg-white border border-amber-200 p-2.5">
                          <p className="text-[11px] text-slate-500">Bỏ qua (trùng)</p>
                          <p className="text-sm font-bold text-brand-amber">{historyDetail.result.skipped} dòng</p>
                        </div>
                        <div className="rounded-lg bg-white border border-red-200 p-2.5">
                          <p className="text-[11px] text-slate-500">Từ chối (tương lai)</p>
                          <p className="text-sm font-bold text-brand-red">{historyDetail.result.rejected_future} dòng</p>
                        </div>
                        <div className="rounded-lg bg-white border border-red-200 p-2.5">
                          <p className="text-[11px] text-slate-500">Từ chối (lỗi cấu trúc)</p>
                          <p className="text-sm font-bold text-brand-red">{historyDetail.result.errors} dòng</p>
                        </div>
                      </div>

                      {historyDetail.result.updated_records && historyDetail.result.updated_records.length > 0 && (
                        <div className="rounded-lg bg-white border border-blue-200 p-2.5 space-y-1.5 text-slate-800">
                          <p className="font-bold text-[11px] text-brand-navy">
                            Nhật ký trước &amp; sau khi cập nhật ({historyDetail.result.updated_records.length} bản ghi):
                          </p>
                          {historyDetail.result.updated_records.map((rec) => (
                            <div
                              key={`hist-upd-${rec.row_number}-${rec.employee_id}-${rec.work_date ?? ''}`}
                              className="text-[11px] font-mono text-slate-700 flex flex-wrap justify-between gap-2 border-t border-slate-100 pt-1"
                            >
                              <span className="font-semibold">
                                {rec.employee_id}
                                {rec.work_date ? ` (${rec.work_date})` : ''}
                              </span>
                              <span>
                                Trước: {shortTime(rec.before.check_in)}–{shortTime(rec.before.check_out)} →{' '}
                                <strong className="text-brand-blue">
                                  Sau: {shortTime(rec.after.check_in)}–{shortTime(rec.after.check_out)}
                                </strong>
                              </span>
                            </div>
                          ))}
                        </div>
                      )}

                      {historyDetail.result.anomaly_scan && (
                        <div className="rounded-lg bg-white border border-blue-200 px-3 py-2 flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2 text-slate-800">
                            <ShieldAlert className="w-4 h-4 text-brand-blue shrink-0" />
                            <span>
                              Tự động quét <strong>R1–R8</strong> kỳ{' '}
                              <strong>{historyDetail.result.anomaly_scan.periods.join(', ')}</strong>: phát hiện{' '}
                              <strong className="text-brand-blue">
                                {historyDetail.result.anomaly_scan.inserted} cảnh báo mới
                              </strong>{' '}
                              (R2: {historyDetail.result.anomaly_scan.by_rule.R2 ?? 0}, R7:{' '}
                              {historyDetail.result.anomaly_scan.by_rule.R7 ?? 0}).
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              const targetP = historyDetail.result?.anomaly_scan?.periods[0];
                              if (targetP) setSelectedPeriod(targetP);
                              setHistoryModalOpen(false);
                              navigate('/anomalies');
                            }}
                            className="px-2.5 py-1 rounded-lg bg-brand-blue text-white text-[11px] font-semibold hover:bg-blue-700"
                          >
                            Xem cảnh báo kỳ này →
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Failed info */}
                  {historyDetail.log.status === 'failed' && historyDetail.result && (
                    <div className="rounded-xl border border-red-200 bg-red-50 p-3.5 text-red-900">
                      <p className="font-bold">Phiên nhập thất bại (đã rollback an toàn)</p>
                      {historyDetail.result.error && <p className="mt-1 font-mono text-[11px]">{historyDetail.result.error}</p>}
                    </div>
                  )}

                  {/* Full Row-Level Snapshot Viewer */}
                  {historyDetail.has_snapshot && historyDetail.preview ? (
                    <div className="space-y-3">
                      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                        <div className="rounded-lg border border-brand-border bg-slate-50 p-2.5">
                          <p className="text-[11px] text-slate-500">Tổng số dòng</p>
                          <p className="text-base font-bold text-slate-900">{historyDetail.preview.summary.rows_total}</p>
                        </div>
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-2.5">
                          <p className="text-[11px] text-slate-500">Đủ ĐK nhập</p>
                          <p className="text-base font-bold text-brand-green">{historyDetail.preview.summary.rows_valid}</p>
                        </div>
                        <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-2.5">
                          <p className="text-[11px] text-slate-500">Cảnh báo nghiệp vụ</p>
                          <p className="text-base font-bold text-brand-amber">{historyDetail.preview.summary.rows_warning}</p>
                        </div>
                        <div className="rounded-lg border border-sky-200 bg-sky-50/50 p-2.5">
                          <p className="text-[11px] text-slate-500">Trùng lặp</p>
                          <p className="text-base font-bold text-brand-teal">{historyDetail.preview.summary.rows_duplicate}</p>
                        </div>
                        <div className="rounded-lg border border-red-200 bg-red-50/50 p-2.5">
                          <p className="text-[11px] text-slate-500">Lỗi cần sửa</p>
                          <p className="text-base font-bold text-brand-red">{historyDetail.preview.summary.rows_error}</p>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setHistoryTab('valid')}
                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                              historyTab === 'valid' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                            }`}
                          >
                            Đủ điều kiện nhập ({historyDetail.preview.summary.rows_valid})
                          </button>
                          <button
                            type="button"
                            onClick={() => setHistoryTab('duplicate')}
                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                              historyTab === 'duplicate' ? 'bg-brand-amber text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                            }`}
                          >
                            Trùng lặp ({historyDetail.preview.summary.rows_duplicate})
                          </button>
                          <button
                            type="button"
                            onClick={() => setHistoryTab('error')}
                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                              historyTab === 'error' ? 'bg-brand-red text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                            }`}
                          >
                            Lỗi cần sửa ({historyDetail.preview.summary.rows_error})
                          </button>
                        </div>

                        {historyDetail.can_download_errors && historyDetail.log.batch_id && (
                          <button
                            type="button"
                            onClick={() => handleDownloadErrorsForBatch(historyDetail.log.batch_id!)}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-200 bg-red-50 text-xs font-semibold text-brand-red hover:bg-red-100"
                          >
                            <Download className="w-3.5 h-3.5" />
                            Tải CSV dòng lỗi
                          </button>
                        )}
                      </div>

                      {historyTab === 'valid' && (
                        <DataTable
                          columns={buildValidColumns(historyDetail.preview)}
                          data={historyDetail.preview.preview_rows}
                          rowKey={(r, i) => `hist-valid-${r.row_number ?? i}`}
                          emptyTitle="Không có dòng đủ điều kiện nhập"
                        />
                      )}
                      {historyTab === 'duplicate' && (
                        <DataTable
                          columns={buildDuplicateColumns(
                            historyDetail.preview,
                            false,
                            historyDetail.result?.duplicate_decisions
                          )}
                          data={historyDetail.preview.duplicate_rows}
                          rowKey={(r) => `hist-dup-${r.row_number}`}
                          emptyTitle="Không có dòng trùng lặp"
                        />
                      )}
                      {historyTab === 'error' && (
                        <DataTable
                          columns={buildErrorColumns(historyDetail.preview, historyExpandedErrors, setHistoryExpandedErrors)}
                          data={historyDetail.preview.error_rows}
                          rowKey={(r) => `hist-err-${r.row_number}`}
                          emptyTitle="Không có dòng lỗi cấu trúc"
                        />
                      )}
                    </div>
                  ) : (
                    /* Legacy log row created before snapshot storage */
                    <div className="space-y-3">
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                        <div className="rounded-lg border border-brand-border bg-slate-50 p-3">
                          <p className="text-[11px] text-slate-500">Tổng số dòng</p>
                          <p className="text-base font-bold text-slate-900">{historyDetail.log.rows_total}</p>
                        </div>
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
                          <p className="text-[11px] text-slate-500">Đủ ĐK nhập</p>
                          <p className="text-base font-bold text-brand-green">{historyDetail.log.rows_valid}</p>
                        </div>
                        <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3">
                          <p className="text-[11px] text-slate-500">Trùng lặp</p>
                          <p className="text-base font-bold text-brand-amber">{historyDetail.log.rows_duplicate}</p>
                        </div>
                        <div className="rounded-lg border border-red-200 bg-red-50/50 p-3">
                          <p className="text-[11px] text-slate-500">Lỗi cần sửa</p>
                          <p className="text-base font-bold text-brand-red">{historyDetail.log.rows_error}</p>
                        </div>
                      </div>
                      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3.5 text-slate-600 leading-relaxed">
                        Phiên xem trước này được tạo trước khi bật tính năng lưu trữ chi tiết từng dòng trong cơ sở dữ liệu.
                        Hãy tải lại tệp Excel/CSV một lần nữa — từ bây giờ hệ thống tự động lưu đầy đủ toàn bộ bảng chi tiết (cảnh báo nghiệp vụ, đối chiếu trùng lặp, dòng lỗi và kết quả xác nhận) để bạn có thể xem lại hoặc mở lại xác nhận bất kỳ lúc nào.
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-5 py-3.5 border-t border-brand-border bg-slate-50/70 flex flex-wrap items-center justify-end gap-2.5">
              {historyDetail?.can_resume_confirm && (
                <button
                  type="button"
                  onClick={handleResumeFromHistory}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-green text-white text-xs font-semibold hover:bg-emerald-800"
                >
                  <Play className="w-3.5 h-3.5" />
                  Mở lại để xác nhận nhập
                </button>
              )}
              <button
                type="button"
                onClick={() => setHistoryModalOpen(false)}
                className="px-4 py-2 rounded-lg border border-brand-border bg-white text-xs font-semibold text-slate-700 hover:bg-slate-100"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        isOpen={confirmOpen}
        title={
          effectiveUpdateCount > 0
            ? `Xác nhận nhập & cập nhật ${effectiveUpdateCount} bản ghi đã tồn tại?`
            : 'Xác nhận ghi dữ liệu vào hệ thống?'
        }
        description={
          preview
            ? `Phiên ${preview.batch_id} sẽ thực hiện: ${effectiveInsertCount} dòng thêm mới, ${effectiveUpdateCount} dòng cập nhật từ Excel, ${effectiveSkipCount} dòng trùng giữ nguyên (bỏ qua)${
                effectiveFutureBlockedCount > 0
                  ? `, ${effectiveFutureBlockedCount} dòng ngày tương lai bị chặn`
                  : ''
              }, và ${preview.summary.rows_error} dòng lỗi không được nhập.${
                effectiveUpdateCount > 0
                  ? ' Các bản ghi cập nhật sẽ được kiểm tra đồng thời trong cơ sở dữ liệu trước khi ghi đè trực tiếp (không tạo trùng khóa) và lưu đầy đủ nhật ký trước/sau.'
                  : ''
              } Sau khi hoàn tất, hệ thống tự động chạy lại rà soát R1–R8 cho toàn bộ kỳ dữ liệu bị ảnh hưởng.`
            : ''
        }
        confirmLabel={buildConfirmButtonLabel()}
        isLoading={confirming}
        onConfirm={handleConfirmImport}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
};
