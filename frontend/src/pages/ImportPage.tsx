import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Download,
  FileSpreadsheet,
  FileUp,
  History,
  Upload,
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

interface PreviewResponse {
  batch_id: string;
  file_name: string;
  data_type: ImportDataType;
  summary: {
    rows_total: number;
    rows_valid: number;
    rows_error: number;
    rows_duplicate: number;
  };
  preview_rows: Record<string, unknown>[];
  duplicate_rows: Array<{ row_number: number; reason: string; data: Record<string, unknown> }>;
  error_rows: Array<{ row_number: number; error: string; raw: Record<string, unknown> }>;
}

interface ConfirmResult {
  status: string;
  batch_id: string;
  data_type: string;
  inserted: number;
  updated: number;
  skipped: number;
  errors: number;
}

interface ImportLogRow {
  id: number;
  file_name: string;
  data_type: string;
  uploaded_by: string;
  uploaded_by_username?: string | null;
  rows_total: number;
  rows_valid: number;
  rows_error: number;
  rows_duplicate: number;
  status: string;
  created_at: string;
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

export const ImportPage: React.FC = () => {
  const { showToast } = useAuth();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [dataType, setDataType] = useState<ImportDataType>('attendance');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState<boolean>(false);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'valid' | 'duplicate' | 'error'>('valid');
  const [duplicatePolicy, setDuplicatePolicy] = useState<'skip' | 'update'>('skip');
  const [confirmOpen, setConfirmOpen] = useState<boolean>(false);
  const [confirming, setConfirming] = useState<boolean>(false);
  const [lastResult, setLastResult] = useState<ConfirmResult | null>(null);

  const [logs, setLogs] = useState<ImportLogRow[]>([]);
  const [loadingLogs, setLoadingLogs] = useState<boolean>(true);
  const [logsError, setLogsError] = useState<string | null>(null);

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
    try {
      const fd = new FormData();
      fd.append('data_type', dataType);
      fd.append('file', selectedFile);
      const res = await apiFetch<PreviewResponse>('/imports/preview', {
        method: 'POST',
        body: fd,
      });
      setPreview(res);
      if (res.summary.rows_error > 0) {
        setActiveTab('error');
      } else if (res.summary.rows_valid > 0) {
        setActiveTab('valid');
      } else {
        setActiveTab('duplicate');
      }
      showToast(`Đã kiểm tra ${res.summary.rows_total} dòng dữ liệu từ tệp ${res.file_name}.`, 'info');
      loadLogs();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể phân tích file tải lên.', 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleDownloadErrors = async () => {
    if (!preview) return;
    try {
      await apiDownload(`/imports/errors/${preview.batch_id}`, `errors_${preview.batch_id}.csv`);
      showToast('Đã tải tệp CSV danh sách dòng lỗi.', 'success');
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể tải danh sách dòng lỗi.', 'error');
    }
  };

  const handleConfirmImport = async () => {
    if (!preview) return;
    setConfirming(true);
    try {
      const res = await apiFetch<ConfirmResult>(`/imports/confirm/${preview.batch_id}`, {
        method: 'POST',
        body: JSON.stringify({ duplicate_policy: duplicatePolicy }),
      });
      setLastResult(res);
      setPreview(null);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      setConfirmOpen(false);
      showToast(`Nhập dữ liệu thành công: thêm ${res.inserted}, cập nhật ${res.updated}, bỏ qua ${res.skipped}.`, 'success');
      loadLogs();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Xác nhận nhập dữ liệu thất bại.', 'error');
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
    { key: 'rows_valid', header: 'Hợp lệ', render: (r) => <span className="text-brand-green font-semibold">{r.rows_valid}</span> },
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
  ];

  const validColumns: ColumnDef<Record<string, unknown>>[] =
    preview && preview.preview_rows.length > 0
      ? Object.keys(preview.preview_rows[0]).map((k) => ({
          key: k,
          header: k,
          render: (row) => String(row[k] ?? '—'),
        }))
      : [];

  return (
    <div className="space-y-6">
      {/* Step 1 & 2: Choose data type + download template + upload */}
      <div className="rounded-card border border-brand-border bg-white p-6 shadow-sm space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Nhập dữ liệu từ Excel / CSV (Staging & Rollback an toàn)</h2>
            <p className="mt-1 text-xs text-slate-500">
              Hệ thống kiểm tra định dạng, chặn ký tự công thức độc hại (Formula Injection) và cho xem trước toàn bộ dòng hợp lệ / trùng / lỗi trước khi ghi vào CSDL.
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
            <div className="w-11 h-11 rounded-xl bg-white border border-brand-border flex items-center justify-center text-brand-blue shadow-sm">
              <FileUp className="w-5 h-5" />
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-900">
                {selectedFile ? selectedFile.name : 'Chọn tệp dữ liệu (.xlsx hoặc .csv, tối đa 5 MB)'}
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                {selectedFile
                  ? `Dung lượng: ${(selectedFile.size / 1024).toFixed(1)} KB — Sẵn sàng kiểm tra`
                  : 'Bước 1: Chọn file → Bước 2: Kiểm tra & xem trước → Bước 3: Xác nhận nhập.'}
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

      {/* Last confirmed result banner */}
      {lastResult && (
        <div className="rounded-card border border-emerald-200 bg-emerald-50/70 p-4 flex items-center justify-between gap-4 text-xs text-emerald-900">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-brand-green shrink-0" />
            <div>
              <p className="font-bold">Đã hoàn tất nhập dữ liệu phiên {lastResult.batch_id}</p>
              <p className="mt-0.5">
                Thêm mới: <strong>{lastResult.inserted}</strong> • Cập nhật: <strong>{lastResult.updated}</strong> • Bỏ qua trùng:{' '}
                <strong>{lastResult.skipped}</strong> • Dòng lỗi không nhập: <strong>{lastResult.errors}</strong>
              </p>
            </div>
          </div>
          <StatusBadge label="Thành công" variant="approved" />
        </div>
      )}

      {/* Step 3 & 4: Preview Staging Results */}
      {preview && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard title="Tổng số dòng đọc được" value={preview.summary.rows_total} tone="blue" icon={<FileSpreadsheet className="w-5 h-5" />} />
            <KpiCard title="Dòng hợp lệ (sẵn sàng thêm)" value={preview.summary.rows_valid} tone="green" icon={<CheckCircle2 className="w-5 h-5" />} />
            <KpiCard title="Dòng trùng khóa" value={preview.summary.rows_duplicate} tone="amber" icon={<Copy className="w-5 h-5" />} />
            <KpiCard title="Dòng lỗi cần sửa" value={preview.summary.rows_error} tone="red" icon={<AlertTriangle className="w-5 h-5" />} />
          </div>

          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab('valid')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                    activeTab === 'valid' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  Hợp lệ ({preview.summary.rows_valid})
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
                  Lỗi ({preview.summary.rows_error})
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

                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-600 font-medium">Xử lý dòng trùng:</span>
                  <select
                    value={duplicatePolicy}
                    onChange={(e) => setDuplicatePolicy(e.target.value as 'skip' | 'update')}
                    className="px-2.5 py-1.5 rounded-lg border border-brand-border bg-brand-bg/60 text-xs text-slate-700"
                  >
                    <option value="skip">Bỏ qua dòng trùng (Skip)</option>
                    <option value="update">Cập nhật dòng trùng (Update)</option>
                  </select>
                </div>

                <button
                  type="button"
                  disabled={preview.summary.rows_valid === 0 && (preview.summary.rows_duplicate === 0 || duplicatePolicy === 'skip')}
                  onClick={() => setConfirmOpen(true)}
                  className="px-4 py-2 rounded-lg bg-brand-green text-white text-xs font-semibold hover:bg-emerald-800 disabled:opacity-50"
                >
                  Xác nhận nhập vào hệ thống
                </button>
              </div>
            </div>

            {activeTab === 'valid' && (
              <DataTable
                columns={validColumns}
                data={preview.preview_rows}
                rowKey={(_, i) => `valid-${i}`}
                emptyTitle="Không có dòng hợp lệ mới"
              />
            )}

            {activeTab === 'duplicate' && (
              <DataTable
                columns={[
                  { key: 'row_number', header: 'Dòng Excel' },
                  { key: 'reason', header: 'Lý do trùng lặp' },
                  {
                    key: 'data',
                    header: 'Dữ liệu chuẩn hóa',
                    render: (r) => <span className="font-mono text-[11px] text-slate-600">{JSON.stringify(r.data)}</span>,
                  },
                ]}
                data={preview.duplicate_rows}
                rowKey={(r) => `dup-${r.row_number}`}
                emptyTitle="Không có dòng trùng lặp"
              />
            )}

            {activeTab === 'error' && (
              <DataTable
                columns={[
                  { key: 'row_number', header: 'Dòng Excel' },
                  {
                    key: 'error',
                    header: 'Chi tiết lỗi',
                    render: (r) => <span className="text-brand-red font-medium whitespace-normal">{r.error}</span>,
                  },
                  {
                    key: 'raw',
                    header: 'Dữ liệu gốc',
                    render: (r) => <span className="font-mono text-[11px] text-slate-500">{JSON.stringify(r.raw)}</span>,
                  },
                ]}
                data={preview.error_rows}
                rowKey={(r) => `err-${r.row_number}`}
                emptyTitle="Không phát hiện lỗi dữ liệu"
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

      <ConfirmModal
        isOpen={confirmOpen}
        title="Xác nhận ghi dữ liệu vào hệ thống?"
        description={
          preview
            ? `Phiên ${preview.batch_id} sẽ nhập ${preview.summary.rows_valid} dòng hợp lệ${
                duplicatePolicy === 'update'
                  ? ` và cập nhật ${preview.summary.rows_duplicate} dòng trùng`
                  : ` (bỏ qua ${preview.summary.rows_duplicate} dòng trùng)`
              }. Toàn bộ giao dịch được bảo vệ atomic rollback nếu có sự cố.`
            : ''
        }
        confirmLabel="Xác nhận nhập ngay"
        isLoading={confirming}
        onConfirm={handleConfirmImport}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
};
