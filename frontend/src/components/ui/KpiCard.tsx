import React from 'react';

export type KpiTone = 'blue' | 'teal' | 'amber' | 'red' | 'green';

export interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  tooltip?: string;
  tone?: KpiTone;
  icon?: React.ReactNode;
  onClick?: () => void;
}

const toneClasses: Record<KpiTone, string> = {
  blue: 'bg-blue-600/10 text-brand-blue',
  teal: 'bg-teal-600/10 text-brand-teal',
  amber: 'bg-amber-600/10 text-brand-amber',
  red: 'bg-red-600/10 text-brand-red',
  green: 'bg-emerald-700/10 text-brand-green',
};

export const KpiCard: React.FC<KpiCardProps> = ({
  title,
  value,
  subtitle,
  tooltip,
  tone = 'blue',
  icon,
  onClick,
}) => {
  return (
    <div
      onClick={onClick}
      title={tooltip}
      className={`rounded-card border border-brand-border bg-white p-5 shadow-sm transition-all ${
        onClick ? 'cursor-pointer hover:border-brand-blue/50 hover:shadow-md' : ''
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <div
          className={`w-10 h-10 rounded-xl flex items-center justify-center font-semibold ${toneClasses[tone]}`}
        >
          {icon || <span className="w-3 h-3 rounded-full bg-current" />}
        </div>
        {tooltip && (
          <span className="text-[11px] text-slate-400" title={tooltip}>
            ⓘ Công thức
          </span>
        )}
      </div>
      <p className="text-xs font-medium text-slate-500">{title}</p>
      <p className="mt-1 text-2xl font-bold text-slate-900 tracking-tight">{value}</p>
      {subtitle && <p className="mt-1.5 text-xs font-medium text-brand-teal">{subtitle}</p>}
    </div>
  );
};
