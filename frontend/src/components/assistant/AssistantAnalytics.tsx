import React, { useMemo, useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { BarChart3, ChevronDown, ChevronUp, Table2, TrendingUp } from 'lucide-react';
import {
  AskResponse,
  formatCellValueVi,
  getVietnameseColumnLabel,
} from '../../types/assistant';

export interface AssistantAnalyticsProps {
  response: AskResponse;
}

interface DerivedKpi {
  key: string;
  label: string;
  value: string;
  tone: 'blue' | 'teal' | 'amber' | 'green';
}

const KPI_CANDIDATE_KEYS: Array<{ key: string; tone: DerivedKpi['tone'] }> = [
  { key: 'employee_count', tone: 'blue' },
  { key: 'total_work_hours', tone: 'teal' },
  { key: 'on_time_rate_pct', tone: 'green' },
  { key: 'late_days', tone: 'amber' },
  { key: 'late_rate_pct', tone: 'amber' },
  { key: 'total_late_minutes', tone: 'amber' },
  { key: 'annual_leave_balance', tone: 'blue' },
  { key: 'used_annual_days', tone: 'teal' },
  { key: 'remaining_annual_days', tone: 'green' },
  { key: 'leave_days', tone: 'blue' },
  { key: 'total_anomalies', tone: 'amber' },
  { key: 'open_anomalies', tone: 'amber' },
];

const KPI_TONE_STYLES: Record<DerivedKpi['tone'], string> = {
  blue: 'border-blue-100 bg-blue-50/40 text-brand-blue',
  teal: 'border-teal-100 bg-teal-50/40 text-brand-teal',
  amber: 'border-amber-100 bg-amber-50/40 text-brand-amber',
  green: 'border-emerald-100 bg-emerald-50/40 text-brand-green',
};

// Hide pure internal technical ID columns when business name columns are already present
function getDisplayColumns(columns: string[]): string[] {
  const hidden = new Set<string>();
  if (columns.includes('department_name') && columns.includes('department_id')) {
    hidden.add('department_id');
  }
  if (columns.includes('anomaly_id') && columns.includes('rule_code')) {
    hidden.add('anomaly_id');
  }
  if (columns.includes('scope_type') && columns.includes('target_code')) {
    hidden.add('scope_type');
  }
  return columns.filter((c) => !hidden.has(c));
}

/**
 * Verified AI Analytics panel (KPI Cards, LineChart/BarChart, Vietnamese Business Table).
 * Strictly renders ONLY SQL-verified structured data from `response.table` and `response.chart`
 * when `response.status === 'success'`. NEVER extracts or guesses numbers from LLM prose.
 */
export const AssistantAnalytics: React.FC<AssistantAnalyticsProps> = ({ response }) => {
  const [showAllRows, setShowAllRows] = useState(false);

  const isSufficient = response.status === 'success';
  const table = isSufficient ? response.table : null;
  const chart = isSufficient ? response.chart : null;
  const columnLabels = response.column_labels;

  // Build verified KPI cards exclusively from single-row SQL summary records
  const kpiCards = useMemo<DerivedKpi[]>(() => {
    if (!table || table.rows.length !== 1) return [];
    const row = table.rows[0];
    const items: DerivedKpi[] = [];
    for (const candidate of KPI_CANDIDATE_KEYS) {
      const val = row[candidate.key];
      if (typeof val === 'number' && Number.isFinite(val)) {
        items.push({
          key: candidate.key,
          label: getVietnameseColumnLabel(candidate.key, columnLabels),
          value: formatCellValueVi(candidate.key, val),
          tone: candidate.tone,
        });
      }
      if (items.length >= 4) break;
    }
    return items.length >= 2 ? items : [];
  }, [table, columnLabels]);

  const displayColumns = useMemo(
    () => (table ? getDisplayColumns(table.columns) : []),
    [table]
  );

  const hasValidChart = Boolean(
    chart &&
      Array.isArray(chart.data) &&
      chart.data.length >= 2 &&
      chart.xKey &&
      chart.yKey &&
      chart.data.some((d) => typeof d[chart.yKey] === 'number')
  );

  const hasTableRows = Boolean(table && table.rows.length > 0 && displayColumns.length > 0);

  if (!hasValidChart && !hasTableRows && kpiCards.length === 0) {
    return null;
  }

  const totalRows = table?.rows.length ?? 0;
  const visibleRows = table ? (showAllRows ? table.rows : table.rows.slice(0, 10)) : [];
  const isLineChart = chart?.type === 'line';

  return (
    <div className="space-y-3 pt-1" data-testid="assistant-analytics">
      {/* 1. SQL-Verified KPI Cards */}
      {kpiCards.length > 0 && (
        <div
          className="grid grid-cols-2 sm:grid-cols-4 gap-2.5"
          data-testid="assistant-kpi-cards"
        >
          {kpiCards.map((kpi) => (
            <div
              key={kpi.key}
              className={`rounded-xl border px-3 py-2.5 ${KPI_TONE_STYLES[kpi.tone]}`}
            >
              <p className="text-[11px] font-medium text-slate-600 truncate">{kpi.label}</p>
              <p className="mt-0.5 text-lg font-bold tracking-tight text-slate-900">
                {kpi.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* 2. Trend LineChart or Comparison BarChart (only when >=2 grounded data points) */}
      {hasValidChart && chart && (
        <div
          className="rounded-xl border border-brand-border bg-slate-50/50 p-3.5"
          data-testid={isLineChart ? 'assistant-line-chart' : 'assistant-bar-chart'}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-brand-navy">
              {isLineChart ? (
                <TrendingUp className="w-4 h-4 text-brand-blue" />
              ) : (
                <BarChart3 className="w-4 h-4 text-brand-blue" />
              )}
              <span>{chart.label}</span>
            </div>
            <span className="text-[10px] font-medium text-slate-500">
              {isLineChart ? 'Biểu đồ xu hướng' : 'Biểu đồ so sánh'} · {chart.data.length} điểm dữ liệu
            </span>
          </div>
          <div className="h-52 w-full">
            <ResponsiveContainer width="100%" height="100%">
              {isLineChart ? (
                <LineChart data={chart.data} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E4EAF2" />
                  <XAxis dataKey={chart.xKey} tick={{ fontSize: 11, fill: '#475569' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#475569' }} width={40} />
                  <Tooltip
                    contentStyle={{
                      borderRadius: '10px',
                      borderColor: '#E4EAF2',
                      fontSize: '12px',
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey={chart.yKey}
                    name={chart.label}
                    stroke="#2563EB"
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: '#2563EB', strokeWidth: 2, stroke: '#ffffff' }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              ) : (
                <BarChart data={chart.data} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E4EAF2" />
                  <XAxis dataKey={chart.xKey} tick={{ fontSize: 11, fill: '#475569' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#475569' }} width={40} />
                  <Tooltip
                    contentStyle={{
                      borderRadius: '10px',
                      borderColor: '#E4EAF2',
                      fontSize: '12px',
                    }}
                  />
                  <Bar
                    dataKey={chart.yKey}
                    name={chart.label}
                    fill="#2563EB"
                    radius={[5, 5, 0, 0]}
                    maxBarSize={44}
                  />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* 3. Business Data Table with 100% Vietnamese Column Labels */}
      {hasTableRows && (
        <div
          className="rounded-xl border border-brand-border bg-white overflow-hidden"
          data-testid="assistant-data-table"
        >
          <div className="px-3 py-2 bg-slate-50 border-b border-brand-border flex items-center justify-between">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-600">
              <Table2 className="w-3.5 h-3.5 text-brand-blue" />
              Bảng dữ liệu đối chiếu ({totalRows} bản ghi)
            </span>
            {totalRows > 10 && (
              <button
                type="button"
                onClick={() => setShowAllRows((prev) => !prev)}
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-blue hover:underline"
              >
                {showAllRows ? (
                  <>
                    Thu gọn <ChevronUp className="w-3.5 h-3.5" />
                  </>
                ) : (
                  <>
                    Xem đầy đủ {totalRows} dòng <ChevronDown className="w-3.5 h-3.5" />
                  </>
                )}
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-slate-50/70 border-b border-brand-border">
                <tr>
                  {displayColumns.map((col) => (
                    <th
                      key={col}
                      className="px-3 py-2 font-semibold text-slate-600 whitespace-nowrap"
                    >
                      {getVietnameseColumnLabel(col, columnLabels)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-border">
                {visibleRows.map((row, rIdx) => (
                  <tr key={rIdx} className="hover:bg-brand-bg/50 transition-colors">
                    {displayColumns.map((col) => (
                      <td
                        key={col}
                        className={`px-3 py-2 text-slate-700 ${
                          col === 'explanation' || col === 'reason'
                            ? 'min-w-[220px] max-w-[360px]'
                            : 'whitespace-nowrap'
                        }`}
                      >
                        {formatCellValueVi(col, row[col])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
