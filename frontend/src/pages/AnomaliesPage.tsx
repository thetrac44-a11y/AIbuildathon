import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { RefreshCw, X, CheckCircle2, EyeOff } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { KpiCard } from '../components/ui/KpiCard';
import { FilterBar } from '../components/ui/FilterBar';
import { DataTable, ColumnDef } from '../components/ui/DataTable';
import { StatusBadge, BadgeVariant } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface AnomalyRow {
  anomaly_id: number;
  employee_id: string | null;
  full_name: string | null;
  department_id: string | null;
  department_name: string | null;
  scope_type: 'employee' | 'department';
  rule_code: string;
  anomaly_type: string;
  severity: 'high' | 'medium' | 'low';
  period: string;
  evidence_data: Record<string, unknown>;
  explanation: string;
  review_status: 'open' | 'confirmed' | 'dismissed';
  reviewed_by: string | null;
  review_note: string | null;
  detected_at: string;
  can_review: boolean;
}

interface AnomaliesResponse {
  total: number;
  summary: {
    total: number;
    open: number;
    confirmed: number;
    dismissed: number;
    high: number;
    medium: number;
    low: number;
  };
  items: AnomalyRow[];
}

const RULE_TITLES: Record<string, string> = {
  R1: 'Đi muộn lặp lại',
  R2: 'Thiếu chấm công',
  R3: 'Làm thiếu giờ chuẩn',
  R4: 'Nghỉ sát ngày lễ',
  R5: 'Nghỉ trùng phòng ban',
  R6: 'Giờ chấm trùng từng giây',
  R7: 'Chấm công ngày nghỉ',
  R8: 'Vượt quỹ phép năm',
};

const SEV_VN: Record<string, string> = { high: 'Cao', medium: 'Trung bình', low: 'Thấp' };
const REV_VN: Record<string, { label: string; variant: BadgeVariant }> = {
  open: { label: 'Mở', variant: 'open' },
  confirmed: { label: 'Đã xác nhận', variant: 'confirmed' },
  dismissed: { label: 'Đã bỏ qua', variant: 'dismissed' },
};

export const AnomaliesPage: React.FC = () => {
  const { user, selectedPeriod, showToast } = useAuth();
  const { anomalyId } = useParams<{ anomalyId?: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<AnomaliesResponse | null>(null);
  // BUG-01: Default to false so AnomaliesPage syncs strictly with Topbar selectedPeriod (matching Dashboard)
  const [filterAllPeriods, setFilterAllPeriods] = useState(false);
  const [severity, setSeverity] = useState('all');
  const [ruleCode, setRuleCode] = useState('all');
  const [reviewStatus, setReviewStatus] = useState('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AnomalyRow | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadAnomalies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        severity,
        rule_code: ruleCode,
        review_status: reviewStatus,
      });
      if (!filterAllPeriods) qs.set('period', selectedPeriod);
      if (search.trim()) qs.set('search', search.trim());
      const res = await apiFetch<AnomaliesResponse>(`/anomalies?${qs.toString()}`);
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải danh sách cảnh báo.');
    } finally {
      setLoading(false);
    }
  }, [severity, ruleCode, reviewStatus, filterAllPeriods, selectedPeriod, search]);

  useEffect(() => {
    loadAnomalies();
  }, [loadAnomalies]);

  // BUG-09: Load specific anomaly detail from direct URL /anomalies/:anomalyId with 403/404 handling
  useEffect(() => {
    if (!anomalyId) {
      setDetailError(null);
      return;
    }
    const parsedId = Number(anomalyId);
    if (!Number.isInteger(parsedId) || parsedId <= 0) {
      setSelected(null);
      setDetailError('Mã cảnh báo trong đường dẫn không hợp lệ.');
      return;
    }

    let cancelled = false;
    setDetailError(null);
    apiFetch<AnomalyRow>(`/anomalies/${parsedId}`)
      .then((item) => {
        if (cancelled) return;
        setSelected(item);
        setReviewNote(item.review_note ?? '');
      })
      .catch((err) => {
        if (cancelled) return;
        setSelected(null);
        setDetailError(
          err instanceof ApiError
            ? err.message
            : 'Không thể tải chi tiết cảnh báo bất thường.'
        );
      });

    return () => {
      cancelled = true;
    };
  }, [anomalyId]);

  const closeDetailModal = () => {
    setSelected(null);
    setDetailError(null);
    if (anomalyId) {
      navigate('/anomalies', { replace: true });
    }
  };

  const handleScan = async () => {
    setScanning(true);
    try {
      const res = await apiFetch<{ total_detected: number; inserted: number }>('/anomalies/scan', {
        method: 'POST',
      });
      showToast(`Đã quét 8 quy tắc R1–R8: phát hiện ${res.total_detected} cảnh báo (${res.inserted} mới).`, 'success');
      loadAnomalies();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Quét bất thường thất bại.', 'error');
    } finally {
      setScanning(false);
    }
  };

  const handleReview = async (newStatus: 'confirmed' | 'dismissed') => {
    if (!selected) return;
    setSubmitting(true);
    try {
      await apiFetch(`/anomalies/${selected.anomaly_id}/review`, {
        method: 'POST',
        body: JSON.stringify({ review_status: newStatus, review_note: reviewNote }),
      });
      showToast(
        newStatus === 'confirmed' ? 'Đã xác nhận cần xử lý cảnh báo.' : 'Đã bỏ qua cảnh báo.',
        'success'
      );
      setSelected(null);
      setReviewNote('');
      if (anomalyId) {
        navigate('/anomalies', { replace: true });
      }
      loadAnomalies();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể cập nhật trạng thái cảnh báo.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnDef<AnomalyRow>[] = [
    {
      key: 'target',
      header: 'Đối tượng',
      render: (r) =>
        r.scope_type === 'department' ? (
          <div className="flex items-center gap-2">
            <StatusBadge label="Cấp phòng" variant="info" />
            <span className="font-semibold">{r.department_name}</span>
          </div>
        ) : (
          <span>
            <strong>{r.employee_id}</strong> · {r.full_name}
          </span>
        ),
    },
    {
      key: 'rule_code',
      header: 'Quy tắc (R1–R8)',
      render: (r) => (
        <span>
          <strong>{r.rule_code}</strong> – {RULE_TITLES[r.rule_code] ?? r.anomaly_type}
        </span>
      ),
    },
    { key: 'period', header: 'Kỳ' },
    {
      key: 'severity',
      header: 'Mức độ',
      render: (r) => <StatusBadge label={SEV_VN[r.severity]} variant={r.severity} />,
    },
    {
      key: 'review_status',
      header: 'Trạng thái',
      render: (r) => {
        const st = REV_VN[r.review_status] ?? { label: r.review_status, variant: 'info' as BadgeVariant };
        return <StatusBadge label={st.label} variant={st.variant} />;
      },
    },
  ];

  return (
    <div className="space-y-5">
      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <KpiCard
            title="Tổng cảnh báo (R1–R8)"
            value={data.summary.total}
            subtitle={filterAllPeriods ? 'Phạm vi: Tất cả kỳ (6 tháng)' : `Phạm vi: Kỳ ${selectedPeriod}`}
            tone="blue"
          />
          <KpiCard title="Mức độ cao" value={data.summary.high} tone="red" />
          <KpiCard
            title="Đang mở (chờ xem xét)"
            value={data.summary.open}
            subtitle={filterAllPeriods ? 'Tất cả kỳ' : `Khớp Dashboard kỳ ${selectedPeriod}`}
            tone="amber"
          />
          <KpiCard title="Đã xác nhận xử lý" value={data.summary.confirmed} tone="green" />
        </div>
      )}

      <FilterBar
        searchPlaceholder="Tìm mã NV, tên hoặc phòng ban..."
        searchValue={search}
        onSearchChange={user?.role !== 'employee' ? setSearch : undefined}
        selectLabel="Mức độ"
        selectValue={severity}
        onSelectChange={setSeverity}
        selectOptions={[
          { value: 'all', label: 'Tất cả mức độ' },
          { value: 'high', label: 'Cao' },
          { value: 'medium', label: 'Trung bình' },
          { value: 'low', label: 'Thấp' },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={ruleCode}
              onChange={(e) => setRuleCode(e.target.value)}
              className="px-2.5 py-2 text-xs rounded-lg border border-brand-border bg-brand-bg/60"
            >
              <option value="all">Tất cả quy tắc</option>
              {Object.entries(RULE_TITLES).map(([code, label]) => (
                <option key={code} value={code}>
                  {code}: {label}
                </option>
              ))}
            </select>
            <select
              value={reviewStatus}
              onChange={(e) => setReviewStatus(e.target.value)}
              className="px-2.5 py-2 text-xs rounded-lg border border-brand-border bg-brand-bg/60"
            >
              <option value="all">Tất cả trạng thái</option>
              <option value="open">Mở</option>
              <option value="confirmed">Đã xác nhận</option>
              <option value="dismissed">Đã bỏ qua</option>
            </select>
            <label className="inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer px-2">
              <input
                type="checkbox"
                checked={filterAllPeriods}
                onChange={(e) => setFilterAllPeriods(e.target.checked)}
              />
              Tất cả kỳ (6 tháng)
            </label>
            {user?.role !== 'employee' && (
              <button
                type="button"
                disabled={scanning}
                onClick={handleScan}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${scanning ? 'animate-spin' : ''}`} />
                Quét R1–R8
              </button>
            )}
          </div>
        }
      />

      {detailError && (
        <ErrorState
          title="Không thể mở chi tiết cảnh báo"
          message={detailError}
          onRetry={() => {
            setDetailError(null);
            navigate('/anomalies', { replace: true });
          }}
        />
      )}

      {error && <ErrorState message={error} onRetry={loadAnomalies} />}
      {loading ? (
        <LoadingSkeleton rows={5} />
      ) : (
        <DataTable
          columns={columns}
          data={data?.items ?? []}
          rowKey={(r) => String(r.anomaly_id)}
          onRowClick={(r) => {
            setSelected(r);
            setReviewNote(r.review_note ?? '');
            navigate(`/anomalies/${r.anomaly_id}`);
          }}
        />
      )}

      {/* Detail Modal matching Mockup Hinh 5 */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-2xl rounded-card border border-brand-border bg-white p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <StatusBadge label={`Mức độ ${SEV_VN[selected.severity]}`} variant={selected.severity} />
                  {selected.scope_type === 'department' && <StatusBadge label="Cảnh báo cấp phòng" variant="info" />}
                  <StatusBadge
                    label={REV_VN[selected.review_status]?.label ?? selected.review_status}
                    variant={REV_VN[selected.review_status]?.variant ?? 'info'}
                  />
                </div>
                <h3 className="text-base font-bold text-slate-900">
                  {selected.rule_code} – {RULE_TITLES[selected.rule_code] ?? selected.anomaly_type}
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  {selected.scope_type === 'department'
                    ? `Phòng ${selected.department_name} · Kỳ ${selected.period}`
                    : `${selected.employee_id} · ${selected.full_name} · Phòng ${selected.department_name} · Kỳ ${selected.period}`}
                </p>
              </div>
              <button type="button" onClick={closeDetailModal}>
                <X className="w-4 h-4 text-slate-500" />
              </button>
            </div>

            <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4">
              <p className="text-xs font-bold text-brand-navy mb-1">Giải thích của hệ thống</p>
              <p className="text-xs text-slate-700 leading-relaxed">{selected.explanation}</p>
            </div>

            <div>
              <p className="text-xs font-bold text-slate-800 mb-2">Bằng chứng dữ liệu gốc (SQL Evidence)</p>
              <pre className="rounded-xl border border-brand-border bg-slate-50 p-3.5 text-[11px] text-slate-700 overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(selected.evidence_data, null, 2)}
              </pre>
            </div>

            {selected.can_review && (
              <div className="pt-3 border-t border-brand-border space-y-3">
                <label className="block text-xs font-semibold text-slate-700">
                  Ghi chú xem xét của quản lý / HR
                </label>
                <textarea
                  rows={2}
                  value={reviewNote}
                  onChange={(e) => setReviewNote(e.target.value)}
                  placeholder="Ghi chú xác minh (VD: nhân viên đi công tác, đã trao đổi nhắc nhở)..."
                  className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border"
                />
                <div className="flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() => handleReview('dismissed')}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-brand-border text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <EyeOff className="w-3.5 h-3.5" /> Bỏ qua cảnh báo
                  </button>
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() => handleReview('confirmed')}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-green text-white text-xs font-semibold hover:bg-emerald-800"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" /> Xác nhận cần xử lý
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
