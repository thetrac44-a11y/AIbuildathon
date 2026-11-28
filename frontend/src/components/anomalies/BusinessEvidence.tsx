import React from 'react';
import { CalendarDays, ClipboardCheck, Info, ShieldAlert } from 'lucide-react';
import {
  AnomalyEvidenceInput,
  buildBusinessEvidence,
  EvidenceMetricCard,
} from '../../utils/businessEvidence';

export interface BusinessEvidenceProps {
  anomaly: AnomalyEvidenceInput;
}

const CARD_TONE_CLASSES: Record<NonNullable<EvidenceMetricCard['tone']>, string> = {
  default: 'border-brand-border bg-slate-50/80 text-slate-900',
  blue: 'border-blue-200/80 bg-blue-50/50 text-brand-navy',
  amber: 'border-amber-200/80 bg-amber-50/60 text-amber-950',
  red: 'border-red-200/80 bg-red-50/60 text-brand-red',
  teal: 'border-teal-200/80 bg-teal-50/60 text-teal-950',
};

export const BusinessEvidence: React.FC<BusinessEvidenceProps> = ({ anomaly }) => {
  const model = buildBusinessEvidence(anomaly);
  const gridCols =
    model.metrics.length >= 4
      ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4'
      : 'grid-cols-1 sm:grid-cols-3';

  return (
    <div className="space-y-4" data-testid="business-evidence">
      {/* 3. Khối Bằng chứng xác minh */}
      <section className="rounded-xl border border-brand-border bg-white p-4 space-y-3.5">
        <div className="flex items-start justify-between gap-2 pb-2.5 border-b border-brand-border/80">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-brand-blue/10 text-brand-blue flex items-center justify-center shrink-0">
              <ClipboardCheck className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h4 className="text-xs font-bold text-slate-900">Bằng chứng xác minh</h4>
              <p className="text-[11px] text-slate-500 truncate">{model.title}</p>
            </div>
          </div>
        </div>

        {/* Metric summary cards (3–4 clean cards max) */}
        <div className={`grid ${gridCols} gap-3`}>
          {model.metrics.map((metric) => {
            const toneClass = CARD_TONE_CLASSES[metric.tone ?? 'default'];
            return (
              <div
                key={metric.label}
                className={`rounded-xl border px-3.5 py-3 flex flex-col justify-between ${toneClass}`}
              >
                <span className="text-[11px] font-medium text-slate-500">{metric.label}</span>
                <span className="mt-1 text-sm font-bold leading-snug break-words">
                  {metric.value}
                </span>
                {metric.sublabel && (
                  <span className="mt-1 text-[10px] text-slate-500 leading-tight">
                    {metric.sublabel}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Clean tags for dates / employee IDs / leave ranges */}
        {model.tags.length > 0 && (
          <div className="pt-1">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-600 mb-2">
              <CalendarDays className="w-3.5 h-3.5 text-slate-400" />
              <span>{model.tagsTitle ?? 'Chi tiết ghi nhận'}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {model.tags.map((tag, idx) => (
                <span
                  key={`${tag}-${idx}`}
                  className="inline-flex items-center px-2.5 py-1 rounded-md border border-brand-border bg-brand-bg text-[11px] font-medium text-slate-700"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {model.fallbackNote && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 flex items-start gap-2 text-[11px] text-amber-900">
            <ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-0.5 text-brand-amber" />
            <span>{model.fallbackNote}</span>
          </div>
        )}
      </section>

      {/* 4. Phần Nhận xét bằng ngôn ngữ tự nhiên */}
      <section className="rounded-xl border border-blue-200/80 bg-blue-50/60 p-4 space-y-2">
        <div className="flex items-center gap-1.5 text-xs font-bold text-brand-navy">
          <Info className="w-4 h-4 text-brand-blue shrink-0" />
          <span>Nhận xét</span>
        </div>
        <p className="text-xs text-slate-800 leading-relaxed">{model.commentary}</p>
        <p className="text-[11px] text-slate-500 leading-relaxed pt-1 border-t border-blue-200/60">
          {model.disclaimer}
        </p>
      </section>
    </div>
  );
};
